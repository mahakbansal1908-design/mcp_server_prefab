from datetime import date
import json
from pathlib import Path
import requests
import re

from fastmcp import FastMCP
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Column,
    Row,
    Grid,
    Heading,
    Text,
    Muted,
    Badge,
    Separator,
    Image,
    Markdown,
)

mcp = FastMCP("PrefabServer")

# Tool 1: Fetch something from the internet
@mcp.tool()
def fetch_content(url: str) -> str:
    """Fetch content from a URL."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        response = requests.get(url, headers=headers, timeout=10)
        
        # Extract Open Graph image if available
        og_image = re.search(r'<meta property="og:image" content="([^"]+)"', response.text)
        og_image_url = og_image.group(1) if og_image else ""
        
        # Find some candidate image urls
        candidate_images = re.findall(r'<img[^>]*src="([^"]+)"', response.text)
        # Filter out common icons/trackers and take top 5
        candidate_images = [img for img in candidate_images if not any(x in img for x in ['.gif', 'avatar', 'logo', 'icon', 'tracker'])]
        # Ensure absolute URLs
        candidate_images = [img if img.startswith('http') else url + img for img in candidate_images][:5]
        
        # Remove script and style elements
        text = re.sub(r'<script[^>]*>([\s\S]*?)<\/script>', ' ', response.text)
        text = re.sub(r'<style[^>]*>([\s\S]*?)<\/style>', ' ', text)
        
        # Remove other HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Prepend images to content
        img_header = f"--- Found Images ---\nOG Image: {og_image_url}\nCandidate Images: {', '.join(candidate_images)}\n\n"
        
        return img_header + text[:20000]
    except Exception as e:
        return f"Failed to fetch {url}: {str(e)}"

# Tool 2: Search the internet
@mcp.tool()
def search_internet(query: str) -> str:
    """Search the internet for a query using DuckDuckGo Lite."""
    try:
        url = "https://lite.duckduckgo.com/lite/"
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        response = requests.post(url, data={"q": query}, headers=headers, timeout=10)
        
        text = re.sub(r'<[^>]+>', ' ', response.text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:20000]
    except Exception as e:
        return f"Search failed: {str(e)}"

# Tool 3: CRUD operations
@mcp.tool()
def file_crud(action: str, filename: str, content: str = None) -> str:
    """Read, write, or delete data on disk."""
    p = Path(filename)
    try:
        if action in ["create", "write"]:
            if content is None:
                return "Error: Content is required for write action."
            p.write_text(content, encoding="utf-8")
            return f"Successfully wrote to {filename}"
        elif action == "read":
            if not p.exists():
                return f"Error: File {filename} not found."
            return p.read_text(encoding="utf-8")
        elif action == "delete":
            if not p.exists():
                return f"File {filename} does not exist."
            p.unlink()
            return f"Successfully deleted {filename}"
        else:
            return f"Unknown action: {action}"
    except Exception as e:
        return f"Failed to perform {action} on {filename}: {str(e)}"

# Tool 4: Return Prefab UI
@mcp.tool(app=True)
def view_tiles(data_file: str) -> PrefabApp:
    """Render tiles based on data in a file."""
    p = Path(data_file)
    if not p.exists():
        with PrefabApp() as app:
            Text(f"File {data_file} not found.")
        return app
    
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        with PrefabApp() as app:
            Text(f"Error reading JSON: {e}")
        return app
        
    with PrefabApp(css_class="max-w-6xl mx-auto p-8 bg-gray-50 min-h-screen") as app:
        with Column(gap=8):
            # A cool header with a gradient text
            with Column(gap=2, items="center"):
                Heading("Agentic Dashboard", level=1, css_class="text-5xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-indigo-500 to-purple-600 text-center")
                Muted("Dynamic search results rendered by your AI assistant", css_class="text-lg text-center text-gray-600")
            
            Separator(css_class="my-2 opacity-50")
            
            with Grid(columns=3, gap=8):
                for i, item in enumerate(data):
                    title = item.get("title", "Untitled")
                    image_url = item.get("image_url", "")
                    link = item.get("link", "#")
                    
                    with Card(css_class="overflow-hidden rounded-3xl bg-white hover:shadow-2xl transition-all duration-500 transform hover:-translate-y-2 border border-gray-50 shadow-sm"):
                        if image_url:
                            Image(src=image_url, alt=title, width="100%", css_class="h-56 object-cover w-full")
                        
                        with CardContent(css_class="p-6"):
                            with Column(gap=4):
                                Badge("Indian Vegetarian", css_class="bg-orange-50 text-orange-700 text-xs font-bold w-max px-3 py-1 rounded-full uppercase tracking-wider")
                                
                                CardTitle(title, css_class="text-xl font-bold text-gray-800 leading-tight")
                                
                                Separator(css_class="opacity-30")
                                
                                with Row(justify="between", items="center"):
                                    Markdown(f"[**View Recipe**]({link})", css_class="text-sm text-indigo-600 hover:text-indigo-800 font-semibold transition-colors")
                                    Text("→", css_class="text-indigo-600")
    return app

if __name__ == "__main__":
    mcp.run()
