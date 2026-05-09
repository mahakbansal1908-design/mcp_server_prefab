import asyncio
import json
from pathlib import Path
import subprocess
import sys
import time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from google import genai
from google.genai import types
import os
from dotenv import load_dotenv

# Initialize Gemini Client with the key from .env file
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)
MODEL = "gemini-3.1-flash-lite-preview"

class PrefabServer:
    """Manages the background Prefab UI server."""
    def __init__(self, target: Path, log_path: Path):
        self.target = target
        self.log_path = log_path
        self._proc = None
        self._log = None

    def start(self) -> None:
        self._log = open(self.log_path, "a")
        self._log.write("\n===== restart =====\n")
        self._log.flush()
        # Using shell=True as fallback
        self._proc = subprocess.Popen(
            f"prefab serve {self.target.name}",
            shell=True,
            cwd=self.target.parent,
            stdout=self._log,
            stderr=subprocess.STDOUT,
        )

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            self._proc = None
        if self._log is not None:
            self._log.close()
            self._log = None

    def restart(self) -> None:
        self.stop()
        self.start()

async def run_agent_loop(server_manager: PrefabServer):
    # Configure the MCP server
    server_params = StdioServerParameters(
        command="python3",
        args=["server.py"],
    )

    print("🔌 Connecting to MCP server...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ Connected to MCP server!")

            # Dynamically get list of tools from the server using MCP APIs
            tools_result = await session.list_tools()
            mcp_tools = tools_result.tools
            
            # Format tools list for the prompt
            tools_desc = ""
            for t in mcp_tools:
                tools_desc += f"- Name: {t.name}\n  Description: {t.description}\n  Arguments: {json.dumps(t.inputSchema.get('properties', {}))}\n\n"

            user_prompt = input("\nEnter your prompt (what do you want to know/see?): ").strip()
            
            initial_prompt = f"""You are an agent with access to an MCP server. 
Your goal is to fulfill the user request.
User Request: {user_prompt}

Available Tools:
{tools_desc}

Instructions:
1. You must decide which tool to call next to progress towards the goal.
2. Use the 'search_internet' tool to find information. You MUST select results from at least 3 different domain names to ensure diversity of sources. Do not rely on a single website for all results.
3. The user wants to see a beautiful UI of the information. To do this, you MUST:
   a. Search and fetch data if needed.
   b. **Verify** that the links you plan to use are valid and return successful content by using the 'fetch_content' tool on them before adding them to the file. This is to ensure they are not broken or 404.
   c. Process the verified data and write it to a file named `data.json` using the 'file_crud' tool with action='write'. You MUST use this exact filename for all runs to prevent accumulating multiple files. The file content must be a JSON list of objects, where each object MUST have 'title', 'link', and 'image_url'. Try to extract a valid image URL from the fetched page if possible.
   d. **You MUST provide at least 5 tiles with different content and different, specific links for each SPECIFIC ITEM (e.g., a specific product or article, not a listicle or collection page).** The title of the tile must be the name of the specific item. Do not use the same link for all items.
   e. Call 'view_tiles' with `data.json` to generate the UI. This should be your last step.
4. Return your response in this JSON format:
   {{
     "thought": "Your reasoning for the next step",
     "call_tool": "tool_name",
     "arguments": {{ ... arguments for the tool ... }}
   }}
   If you are finished and have displayed the UI, or if you have a final answer, return:
   {{
     "thought": "I have completed the task.",
     "final_answer": "A summary of what was done or the answer to the user's question."
   }}
   Respond ONLY with a SINGLE JSON object. Do not include any text before or after the JSON. Do not output multiple JSON objects in one response.
"""
            
            # Use types.Content and types.Part to avoid validation errors in strict environments like Python 3.14
            messages = [
                types.Content(
                    role="user",
                    parts=[types.Part(text=initial_prompt)]
                )
            ]

            print(f"\n🤖 Starting agent loop for prompt: '{user_prompt}'")
            
            # Open agent log file
            agent_log = open("agent_llm.log", "a", encoding="utf-8")
            agent_log.write(f"=== Prompt: {user_prompt} ===\n")
            agent_log.write(f"Initial Instructions:\n{initial_prompt}\n\n")
            agent_log.flush()
            
            verified_links = set()
            
            while True:
                response = client.models.generate_content(
                    model=MODEL,
                    contents=messages,
                )
                
                raw_resp = (response.text or "").strip()
                
                # Log LLM response
                agent_log.write(f"--- LLM Response ---\n{raw_resp}\n\n")
                agent_log.flush()
                
                if raw_resp.startswith("```json"):
                    raw_resp = raw_resp.strip("`").split("\n", 1)[1].rsplit("\n", 1)[0]
                elif raw_resp.startswith("```"):
                    raw_resp = raw_resp.strip("`").strip()
                
                decisions = []
                try:
                    decisions.append(json.loads(raw_resp))
                except json.JSONDecodeError as e:
                    if "Extra data" in str(e):
                        print("⚠️ Detected multiple JSON objects. Parsing all of them.")
                        decoder = json.JSONDecoder()
                        pos = 0
                        while pos < len(raw_resp):
                            try:
                                decision, idx = decoder.raw_decode(raw_resp[pos:])
                                decisions.append(decision)
                                pos += idx
                                while pos < len(raw_resp) and raw_resp[pos].isspace():
                                    pos += 1
                            except json.JSONDecodeError as e2:
                                print(f"❌ Failed to parse JSON object at pos {pos}: {e2}")
                                break
                    else:
                        print(f"❌ Failed to parse LLM response as JSON: {e}")
                        print(f"Raw response: {raw_resp}")
                        agent_log.write(f"Error parsing JSON: {e}\n\n")
                        agent_log.flush()
                        break
                except Exception as e:
                    print(f"❌ Unexpected error parsing JSON: {e}")
                    print(f"Raw response: {raw_resp}")
                    agent_log.write(f"Unexpected error parsing JSON: {e}\n\n")
                    agent_log.flush()
                    break

                # Add model response to history (ONCE)
                messages.append(response.candidates[0].content)
                
                tool_results = []
                should_break = False
                
                for decision in decisions:
                    print(f"\n🧠 Agent Thought: {decision.get('thought')}")

                    if "final_answer" in decision:
                        print(f"🏁 Final Answer: {decision['final_answer']}")
                        agent_log.write(f"🏁 Final Answer: {decision['final_answer']}\n\n")
                        agent_log.flush()
                        should_break = True
                        break

                    tool_name = decision.get("call_tool")
                    tool_args = decision.get("arguments", {})

                    if not tool_name:
                        print("❌ No tool name provided by LLM.")
                        agent_log.write("❌ No tool name provided by LLM.\n\n")
                        agent_log.flush()
                        should_break = True
                        break

                    print(f"🛠️ Calling tool '{tool_name}' with args: {tool_args}")
                    
                    # Intercept file_crud to validate unique links and verification
                    if tool_name == "file_crud" and tool_args.get("action") in ["create", "write"]:
                        content = tool_args.get("content")
                        if content:
                            try:
                                data = json.loads(content)
                                if isinstance(data, list) and len(data) > 0:
                                    links = [item.get("link") for item in data if isinstance(item, dict) and "link" in item]
                                    
                                    # Check for uniqueness
                                    if len(links) != len(set(links)):
                                        print("⚠️ Detected duplicate links! Telling model to retry.")
                                        agent_log.write("Validation Failed: Duplicate links detected. Rejecting write and requesting retry.\n\n")
                                        agent_log.flush()
                                        
                                        tool_results.append(f"Error: All links in the JSON data must be unique. You provided duplicate links. Please search for specific recipes to get unique links for each dish.")
                                        continue 
                                    
                                    # Check for verification
                                    unverified = [link for link in links if link not in verified_links]
                                    if unverified:
                                        print(f"⚠️ Detected unverified links: {unverified}! Telling model to retry.")
                                        agent_log.write(f"Validation Failed: Unverified links detected: {unverified}. Rejecting write and requesting retry.\n\n")
                                        agent_log.flush()
                                        
                                        tool_results.append(f"Error: You must verify all links using 'fetch_content' before adding them to the file. The following links were not verified: {unverified}. Please fetch content for these URLs to verify them.")
                                        continue
                            except json.JSONDecodeError:
                                pass
                    
                    try:
                        result = await session.call_tool(tool_name, tool_args)
                        print(f"📥 Tool result received.")
                        
                        # Log tool result
                        tool_content = "Success"
                        if result.content:
                            tool_content = result.content[0].text
                        agent_log.write(f"--- Tool Result ({tool_name}) ---\n{tool_content}\n\n")
                        agent_log.flush()
                        
                        # Track verified links
                        if tool_name == "fetch_content" and "url" in tool_args:
                            url = tool_args["url"]
                            if not tool_content.startswith("Failed to fetch"):
                                verified_links.add(url)
                                print(f"✅ Verified link: {url}")
                        
                        # Handle special case for view_tiles which returns UI spec
                        if tool_name == "view_tiles":
                            ui_spec = result.structuredContent if hasattr(result, 'structuredContent') else None
                            if ui_spec:
                                Path("ui_spec.json").write_text(json.dumps(ui_spec, indent=2), encoding="utf-8")
                                print("🎉 UI spec saved to ui_spec.json!")
                                print("🔄 Restarting Prefab UI server...")
                                server_manager.restart()
                                
                                import webbrowser
                                print("🌐 Opening dashboard in browser...")
                                webbrowser.open("http://127.0.0.1:5175")
                        
                        tool_results.append(f"Tool '{tool_name}' returned: {tool_content}")
                        
                    except Exception as e:
                        print(f"❌ Error calling tool {tool_name}: {e}")
                        tool_results.append(f"Tool '{tool_name}' failed with error: {e}")
                
                if should_break:
                    break
                    
                # Add all tool results to history as a single user turn
                if tool_results:
                    combined_results = "\n".join(tool_results)
                    messages.append(
                        types.Content(
                            role="user",
                            parts=[types.Part(text=combined_results)]
                        )
                    )

if __name__ == "__main__":
    log_path = Path("prefab_ui.log")
    log_path.write_text("") # Clear logs
    
    agent_log_path = Path("agent_llm.log")
    agent_log_path.write_text("") # Clear agent logs
    
    # Start the Prefab UI server on view_tiles.py
    server_manager = PrefabServer(Path("view_tiles.py"), log_path)
    print(f"Starting Prefab dev server (logs → {log_path.name}) ...")
    server_manager.start()
    time.sleep(2)
    print("🌐 Dashboard available at http://127.0.0.1:5175\n")

    try:
        asyncio.run(run_agent_loop(server_manager))
        print("\n🎉 Dashboard is live! Press Enter to stop the server and exit.")
        input()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nShutting down Prefab UI server...")
        server_manager.stop()
