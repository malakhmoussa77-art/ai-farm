import os, re, json, time, requests

FARM_URL = os.environ["FARM_URL"].rstrip("/")
FARM_KEY = os.environ["FARM_KEY"]
GROQ = os.environ.get("GROQ_API_KEY")
ROLE = os.environ.get("AGENT_ROLE", "researcher")
NODE = os.environ.get("NODE_ID", "gh-node")
RUN_SECONDS = int(os.environ.get("RUN_SECONDS", "300"))
H = {"x-farm-key": FARM_KEY, "content-type": "application/json"}

PROMPTS = {
    "researcher": "Research the goal using the SEARCH results. Return 5 concrete, cited findings.",
    "writer": "Draft clear, punchy copy for the goal. No filler.",
    "analyst": "Analyze the goal. Return the 3 most decision-useful takeaways.",
    "scout": "Scan the SEARCH results. Flag ONLY what is new, urgent, or surprising.",
    "builder": "Write working, minimal, commented code for the goal.",
    "planner": "Break the goal into ordered, testable steps.",
    "memory": "Summarize the goal/result into one tight paragraph for later recall.",
    "commander": "Decompose the goal into 2-5 subtasks. Reply ONLY as JSON: [{\"agent\":\"researcher\",\"goal\":\"...\"}]. Valid agents: researcher, writer, analyst, scout, builder, planner.",
}
SEARCHERS = {"researcher", "scout", "analyst"}

def web_search(q):
    try:
        r = requests.get("https://duckduckgo.com/html/", params={"q": q},
                         headers={"user-agent": "Mozilla/5.0"}, timeout=20)
        hits = re.findall(r'result__snippet[^>]*>(.*?)</a>', r.text)[:5]
        return "\n".join("- " + re.sub("<[^>]+>", "", h).strip() for h in hits) or "(no results)"
    except Exception as e:
        return f"(search failed: {e})"

def think(system, user):
    if not GROQ:
        return "(no GROQ_API_KEY set)"
    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
        headers={"authorization": f"Bearer {GROQ}"},
        json={"model": "llama-3.3-70b-versatile",
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]}, timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def queue(agent, goal, priority=5):
    requests.post(f"{FARM_URL}/command", headers=H,
                  json={"agent": agent, "goal": goal, "priority": priority})

def run(goal):
    ctx = f"\n\nSEARCH RESULTS:\n{web_search(goal)}" if ROLE in SEARCHERS else ""
    out = think(PROMPTS.get(ROLE, PROMPTS["researcher"]), goal + ctx)
    if ROLE == "commander":
        try:
            subs = json.loads(out[out.index("["): out.rindex("]") + 1])
            for s in subs:
                queue(s["agent"], s["goal"])
            return f"Dispatched {len(subs)} subtasks:\n" + "\n".join(f"- {s['agent']}: {s['goal']}" for s in subs)
        except Exception:
            return out
    return out

def beat():
    try:
        requests.post(f"{FARM_URL}/beat", headers=H, json={"id": NODE, "kind": ROLE})
    except Exception:
        pass

def main():
    print(f"[{NODE}] {ROLE} online -> {FARM_URL}")
    end = time.time() + RUN_SECONDS
    last = 0
    while time.time() < end:
        if time.time() - last > 60:
            beat(); last = time.time()
        try:
            task = requests.post(f"{FARM_URL}/claim", headers=H,
                                 json={"agent": ROLE, "node": NODE}, timeout=30).json().get("task")
            if not task:
                time.sleep(6); continue
            print(f"[{NODE}] task {task['id']}: {task['goal'][:60]}")
            result = run(task["goal"])
            requests.post(f"{FARM_URL}/complete", headers=H,
                          json={"id": task["id"], "result": result}, timeout=30)
            print(f"[{NODE}] done {task['id']}")
        except Exception as e:
            print(f"[{NODE}] error: {e}"); time.sleep(8)

if __name__ == "__main__":
    main()
