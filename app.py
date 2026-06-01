import os
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="QuestLog - Eternal Memory AI Dungeon Master")

# Create templates directory if not exists
templates_dir = Path(__file__).resolve().parent / "templates"
templates_dir.mkdir(exist_ok=True)

# In-memory storage for active session details (HP, inventory, etc. as quick cache/fallback)
# If Memori is active, these are dynamically augmented and rebuilt from the Memori database!
session_state = {
    "initialized": False,
    "name": "Hero",
    "char_class": "Warrior",
    "background": "Vagabond",
    "hp": 100,
    "inventory": ["Iron Sword", "Tattered Cloak", "Dry Rations"],
    "quests": ["Begin your journey"],
    "npcs": [{"name": "Town Crier", "relation": "Neutral"}]
}

# Dynamic API Key references (allows setting them via UI!)
keys_config = {
    "memori_api_key": os.getenv("MEMORI_API_KEY", ""),
    "openai_api_key": os.getenv("OPENAI_API_KEY", "")
}

class ChatRequest(BaseModel):
    message: str

class StartRequest(BaseModel):
    name: str
    char_class: str
    background: str

class ConfigUpdateRequest(BaseModel):
    memori_api_key: str
    openai_api_key: str

def get_memori_client():
    """Retrieve or initialize the Memori client based on configured key."""
    api_key = keys_config["memori_api_key"] or os.getenv("MEMORI_API_KEY", "")
    if not api_key:
        return None
    
    try:
        from memori import Memori
        # Initialize Memori SDK with explicit API key in Cloud Mode
        mem = Memori(api_key=api_key)
        # Set attribution for the game
        mem.attribution(entity_id="questlog_player_hero", process_id="dungeon_master_v1")
        return mem
    except Exception as e:
        print(f"Error initializing Memori SDK: {e}")
        return None

def get_openai_client():
    """Retrieve or initialize the OpenAI client based on configured key."""
    api_key = keys_config["openai_api_key"] or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None
    
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key)
    except Exception as e:
        print(f"Error initializing OpenAI: {e}")
        return None

def extract_facts(recall_resp: Any) -> List[str]:
    """Helper to safely extract string facts from any Memori recall response structure."""
    if not recall_resp:
        return []
    
    facts = []
    
    # Check if it's a dictionary (like CloudRecallResponse) with a 'facts' list
    if isinstance(recall_resp, dict) and "facts" in recall_resp:
        items = recall_resp["facts"]
    elif hasattr(recall_resp, "facts"):
        items = recall_resp.facts
    elif isinstance(recall_resp, list):
        items = recall_resp
    else:
        items = [recall_resp]
        
    for item in items:
        if not item:
            continue
        if isinstance(item, str):
            facts.append(item)
        elif isinstance(item, dict):
            content = item.get("content", "")
            if content:
                facts.append(str(content))
            else:
                facts.append(str(item))
        elif hasattr(item, "content"):
            facts.append(str(item.content))
        else:
            facts.append(str(item))
            
    return [f for f in facts if f]

@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest):
    """Dynamically update API keys from the frontend."""
    keys_config["memori_api_key"] = req.memori_api_key.strip()
    keys_config["openai_api_key"] = req.openai_api_key.strip()
    
    # Save to environment for consistency
    if keys_config["memori_api_key"]:
        os.environ["MEMORI_API_KEY"] = keys_config["memori_api_key"]
    if keys_config["openai_api_key"]:
        os.environ["OPENAI_API_KEY"] = keys_config["openai_api_key"]
        
    return {"status": "success", "memori_active": bool(keys_config["memori_api_key"]), "openai_active": bool(keys_config["openai_api_key"])}

@app.get("/api/config")
async def get_config():
    """Check status of API key configuration."""
    mem_key = keys_config["memori_api_key"] or os.getenv("MEMORI_API_KEY", "")
    oa_key = keys_config["openai_api_key"] or os.getenv("OPENAI_API_KEY", "")
    return {
        "memori_active": bool(mem_key),
        "openai_active": bool(oa_key),
        "has_fallback": True
    }

@app.post("/api/start")
async def start_game(req: StartRequest):
    """Start a new adventure and initialize character background story."""
    session_state["initialized"] = True
    session_state["name"] = req.name
    session_state["char_class"] = req.char_class
    session_state["background"] = req.background
    session_state["hp"] = 100
    
    # Determine starter weapon based on class
    weapon = "Iron Sword"
    if req.char_class.lower() == "mage":
        weapon = "Oak Staff"
    elif req.char_class.lower() == "rogue":
        weapon = "Dual Daggers"
    elif req.char_class.lower() == "cleric":
        weapon = "Bronze Mace"
        
    session_state["inventory"] = [weapon, "Leather Waterskin", "Tattered Cloak", "Dry Rations"]
    session_state["quests"] = ["Survive the Darkwoods (Active)"]
    session_state["npcs"] = []

    # Reset Memori session if configured
    mem = get_memori_client()
    if mem:
        try:
            mem.new_session()
            # Capture initial character setup turn to register facts
            initial_user_event = f"Create character named {req.name}, a {req.char_class} with a background of '{req.background}'."
            initial_dm_narration = (
                f"Adventure begins! {req.name} the {req.char_class} steps into the fantasy world of Eldoria. "
                f"Background: {req.background}. Health points (HP): 100. "
                f"Starting equipment: {weapon}, a Leather Waterskin, a Tattered Cloak, and Dry Rations."
            )
            
            # Use Memori Cloud API turn capture which extracts these facts automatically
            mem.capture_agent_turn(
                user_content=initial_user_event,
                assistant_content=initial_dm_narration,
                project_id="questlog",
                session_id=str(mem.config.session_id)
            )
        except Exception as e:
            print(f"Error establishing Memori initial facts: {e}")

    welcome_message = (
        f"**Welcome, {req.name} the {req.char_class}!**\n\n"
        f"Your story begins in the shadowed borders of the Darkwoods. Armed with your *{weapon}*, "
        f"you seek glory and survival. The trees whisper of ancient crypts, dangerous beasts, and hidden fortunes.\n\n"
        f"*What do you do first?*"
    )
    return {"narration": welcome_message, "state": session_state}

@app.post("/api/chat")
async def play_turn(req: ChatRequest):
    """Process a player's action, recall memories, and generate the DM's narrative."""
    if not session_state["initialized"]:
        raise HTTPException(status_code=400, detail="Game not started. Please create a character first.")
        
    openai_client = get_openai_client()
    if not openai_client:
        # Graceful warning if OpenAI key is missing
        return {
            "narration": "[SYSTEM WARNING: OpenAI API key is missing. Please configure it in the settings panel to begin your adventure!]\n\nMeanwhile, you try to move forward, but the world is frozen in stasis.",
            "state": session_state,
            "recalled_facts": []
        }

    mem = get_memori_client()
    recalled_facts = []
    memories_context = ""

    # 1. Memory Recall phase
    if mem:
        try:
            # Recall past relevant actions/items/quests from Memori Cloud
            recall_resp = mem.recall(req.message, limit=8)
            recalled_facts = extract_facts(recall_resp)
            if recalled_facts:
                memories_context = "\n".join([f"- {fact}" for fact in recalled_facts])
        except Exception as e:
            print(f"Error during Memori recall: {e}")

    # 2. Formulate system prompt for the Dungeon Master
    system_prompt = f"""You are the legendary AI Dungeon Master (DM) for a dark fantasy tabletop RPG.
You narrate the world, guide the player, describe NPCs, and respond to player actions.

Keep your descriptions extremely atmospheric, immersive, and concise (under 130 words per turn).
Incorporate the player's current health, inventory, and relations dynamically.

Character Info:
- Name: {session_state['name']}
- Class: {session_state['char_class']}
- Background: {session_state['background']}

Below are the ETERNAL MEMORIES recalled from the player's history (guaranteed facts):
{memories_context if memories_context else "- No prior memories recalled for this specific action."}

Use these memories to maintain perfect consistency! If they have met an NPC, acquired an item, or completed a quest in the memories, acknowledge it.

Rules for updating inventory and stats in your narrative:
- If the player acquires an item, state it clearly in your story (e.g., 'You find a glowing Iron Key').
- If the player takes damage, describe it and state how much HP they lose (e.g., '[HP: -10]').
- If they heal, state it (e.g., '[HP: +15]').
- If they complete a quest or receive a new one, state it clearly (e.g., '[Quest: Find the Lost Crypt] Completed!' or '[Quest: Slay the Wolf Pack] Received!').
- If they meet a character, describe their reaction (e.g., 'Eldrin the Sage nods warily').
"""

    # 3. Call OpenAI for turn narrative
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.message}
            ],
            temperature=0.7
        )
        narration = response.choices[0].message.content
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"OpenAI error: {str(e)}")

    # 4. Save this turn into Memori Cloud so it's committed to eternal memory!
    if mem:
        try:
            mem.capture_agent_turn(
                user_content=req.message,
                assistant_content=narration,
                project_id="questlog",
                session_id=str(mem.config.session_id)
            )
        except Exception as e:
            print(f"Error capturing turn in Memori: {e}")

    # 5. Extract state updates (HP, Inventory, Quests, NPCs) from the turn
    # This allows us to display real-time updates in the sidebar UI!
    # If Memori is active, we ask OpenAI to parse the updated state based on history + narration.
    state_parser_prompt = f"""You are a helper parsing RPG state updates. 
Analyze the player's latest action and the Dungeon Master's narration, and output the updated character sheet in JSON format.

Current state:
HP: {session_state['hp']}
Inventory: {session_state['inventory']}
Quests: {session_state['quests']}
NPCs: {session_state['npcs']}

Player's Action: {req.message}
DM's Narration: {narration}

Output exactly a JSON object (no markdown, no backticks, just raw JSON) matching this structure:
{{
  "hp": integer (current HP between 0 and 100. Adjust based on any damage/healing in the narration. Do not drop below 0 or exceed 100),
  "inventory": [list of strings of all items currently carried. Update if items are picked up, dropped, consumed, or lost],
  "quests": [list of active/completed quests. Add new ones or modify completed ones accordingly],
  "npcs": [list of objects with keys "name" (string) and "relation" (friendly, hostile, neutral, helpful)]
}}
"""
    try:
        parse_resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": state_parser_prompt}],
            temperature=0.1
        )
        import json
        raw_json = parse_resp.choices[0].message.content.strip()
        # Clean backticks if any
        if raw_json.startswith("```"):
            lines = raw_json.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_json = "\n".join(lines).strip()
            
        updated_state = json.loads(raw_json)
        
        # Merge values safely
        session_state["hp"] = max(0, min(100, updated_state.get("hp", session_state["hp"])))
        session_state["inventory"] = updated_state.get("inventory", session_state["inventory"])
        session_state["quests"] = updated_state.get("quests", session_state["quests"])
        session_state["npcs"] = updated_state.get("npcs", session_state["npcs"])
    except Exception as e:
        print(f"Error parsing state updates: {e}")
        # In case of parsing error, we just fallback or do regex analysis
        if "[HP: -" in narration:
            try:
                dmg = int(narration.split("[HP: -")[1].split("]")[0])
                session_state["hp"] = max(0, session_state["hp"] - dmg)
            except: pass
        elif "[HP: +" in narration:
            try:
                heal = int(narration.split("[HP: +")[1].split("]")[0])
                session_state["hp"] = min(100, session_state["hp"] + heal)
            except: pass

    return {
        "narration": narration,
        "state": session_state,
        "recalled_facts": recalled_facts
    }

@app.get("/api/status")
async def get_status():
    """Retrieve player sheet stats."""
    return session_state

@app.get("/api/memories")
async def get_memories():
    """Query Memori Cloud to return all persisted facts/knowledge for debugging."""
    mem = get_memori_client()
    if not mem:
        return {"status": "inactive", "memories": ["Memori Cloud is not configured. Config API keys to unlock eternal memory!"]}
        
    try:
        # Recall general facts to demonstrate background database
        recall_resp = mem.recall("player character background, stats, quest history, items acquired", limit=30)
        facts = extract_facts(recall_resp)
        return {"status": "active", "memories": facts}
    except Exception as e:
        return {"status": "error", "message": str(e), "memories": []}

@app.post("/api/reset")
async def reset_game():
    """Reset player local session details."""
    session_state["initialized"] = False
    session_state["name"] = "Hero"
    session_state["char_class"] = "Warrior"
    session_state["background"] = "Vagabond"
    session_state["hp"] = 100
    session_state["inventory"] = []
    session_state["quests"] = []
    session_state["npcs"] = []
    
    # Try deleting Memories from BYODB if needed (Cloud memories are scoped per session_id)
    mem = get_memori_client()
    if mem:
        try:
            mem.new_session()
        except Exception:
            pass
            
    return {"status": "reset", "state": session_state}

# Serve the Single Page UI
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = templates_dir / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found.")
    with open(index_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

if __name__ == "__main__":
    import uvicorn
    # Bind to environment port or default to 8000
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "127.0.0.1")
    uvicorn.run("app:app", host=host, port=port, reload=True)
