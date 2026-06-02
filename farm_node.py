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
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return "(no TAVILY_API_KEY env reached the agent)"
    try:
        r = requests.post("https://api.tavily.com/search",
                          json={"api_key": key, "query": q,
                                "max_results": 5, "search_depth": "basic"}, timeout=25)
        if r.status_code != 200:
            return "(tavily HTTP %s: %s)" % (r.status_code, r.text[:120])
        res = r.json().get("results", [])
        return "\n".join("- %s: %s" % (x.get("title",""), (x.get("content","") or "")[:220])
                         for x in res) or "(tavily returned 0 results)"
    except Exception as e:
        return f"(search exception: {e})"

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
    search = web_search(goal) if ROLE in SEARCHERS else ""
    ctx = f"\n\nSEARCH RESULTS:\n{search}" if search else ""
    out = think(PROMPTS.get(ROLE, PROMPTS["researcher"]), goal + ctx)
    if ROLE == "commander":
        try:
            subs = json.loads(out[out.index("["): out.rindex("]") + 1])
            for s in subs:
                queue(s["agent"], s["goal"])
            return f"Dispatched {len(subs)} subtasks:\n" + "\n".join(f"- {s['agent']}: {s['goal']}" for s in subs)
        except Exception:
            return out
    if ROLE in SEARCHERS:
        return f"[debug: search returned → {search[:160]}]\n\n{out}"
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
            result = run(task["goal"])
            requests.post(f"{FARM_URL}/complete", headers=H,
                          json={"id": task["id"], "result": result}, timeout=30)
        except Exception as e:
            print(f"[{NODE}] error: {e}"); time.sleep(8)

if __name__ == "__main__":
    main()
