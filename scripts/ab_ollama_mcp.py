#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2,<2", "ollama>=0.4"]
# ///
"""
A/B harness: drive the study-bible MCP from two local Ollama models and
compare tool-calling behaviour + answer quality on the same query.

Usage:
  uv run scripts/ab_ollama_mcp.py "<query>" model_a model_b
  uv run scripts/ab_ollama_mcp.py            # uses defaults below

The MCP server is the remote SSE endpoint the repo already uses.
"""
import asyncio, json, os, sys, time, contextlib

from mcp import ClientSession
from mcp.client.sse import sse_client
import ollama

SSE_URL = os.environ.get("SSE_URL", "https://studybible-mcp.fly.dev/sse")

DEFAULT_QUERY = (
    "Study Psalm 14:1. First look up the verse text, then do a word study on the "
    "Hebrew word translated 'fool', and finally list its cross-references. "
    "Use the study-bible tools for every fact — do not answer from memory. "
    "End with a short synthesis citing what the tools returned."
)
DEFAULT_MODELS = ["ornith-1.5:35b", "qwen3.5:9b"]

SYSTEM = (
    "You are a Bible-study assistant with access to study-bible tools. "
    "Always use the tools to retrieve verses, word studies, cross-references and notes "
    "rather than relying on memory. When you have gathered enough, give a concise answer "
    "grounded only in tool results."
)

SAMPLING = {"temperature": 0.6, "top_p": 0.95, "top_k": 20}
MAX_ROUNDS = 8
TOOL_RESULT_CAP = 2500  # chars fed back to the model per tool result


def to_ollama_tools(mcp_tools):
    out = []
    for t in mcp_tools:
        out.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": (t.description or "")[:1024],
                "parameters": t.inputSchema or {"type": "object", "properties": {}},
            },
        })
    return out


def extract_text(call_result):
    parts = []
    for c in call_result.content:
        txt = getattr(c, "text", None)
        if txt is not None:
            parts.append(txt)
        else:
            parts.append(str(c))
    return "\n".join(parts)


async def run_model(model, query, session, ollama_tools):
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": query},
    ]
    tool_log = []   # list of dicts: {round, name, args, ok, result_preview}
    t0 = time.time()
    final = "(no final answer)"
    for rnd in range(MAX_ROUNDS):
        try:
            resp = await asyncio.to_thread(
                ollama.chat, model=model, messages=messages,
                tools=ollama_tools, options=SAMPLING,
            )
        except Exception as e:
            final = f"(ollama.chat error: {e})"
            break
        msg = resp.message
        messages.append(msg.model_dump())
        calls = msg.tool_calls or []
        if not calls:
            final = (msg.content or "").strip() or "(empty content)"
            break
        for tc in calls:
            name = tc.function.name
            args = tc.function.arguments or {}
            if isinstance(args, str):
                with contextlib.suppress(Exception):
                    args = json.loads(args)
            entry = {"round": rnd, "name": name, "args": args, "ok": False, "preview": ""}
            try:
                res = await session.call_tool(name, dict(args))
                text = extract_text(res)
                entry["ok"] = not getattr(res, "isError", False)
                entry["preview"] = text[:300].replace("\n", " ")
                messages.append({"role": "tool", "tool_name": name,
                                 "content": text[:TOOL_RESULT_CAP]})
            except Exception as e:
                text = f"ERROR calling {name}: {e}"
                entry["preview"] = text[:300]
                messages.append({"role": "tool", "tool_name": name, "content": text})
            tool_log.append(entry)
    else:
        final = "(hit MAX_ROUNDS without finishing)"
    return {
        "model": model,
        "seconds": round(time.time() - t0, 1),
        "rounds": rnd + 1,
        "tool_calls": tool_log,
        "n_tool_calls": len(tool_log),
        "n_tool_ok": sum(1 for e in tool_log if e["ok"]),
        "distinct_tools": sorted({e["name"] for e in tool_log}),
        "final": final,
    }


def print_report(query, valid_tool_names, results):
    print("\n" + "=" * 78)
    print("STUDY-BIBLE MCP  ·  OLLAMA A/B")
    print("=" * 78)
    print(f"Query: {query}\n")
    print(f"MCP tools available: {len(valid_tool_names)}")
    for r in results:
        print("\n" + "-" * 78)
        print(f"MODEL: {r['model']}")
        print(f"  time: {r['seconds']}s | rounds: {r['rounds']} | "
              f"tool calls: {r['n_tool_calls']} (ok {r['n_tool_ok']}) | "
              f"distinct tools: {r['distinct_tools']}")
        bad = [e['name'] for e in r['tool_calls'] if e['name'] not in valid_tool_names]
        if bad:
            print(f"  ⚠ hallucinated/unknown tool names: {sorted(set(bad))}")
        print("  --- tool-call trace ---")
        for e in r['tool_calls']:
            flag = "✓" if e['ok'] else "✗"
            known = "" if e['name'] in valid_tool_names else " [UNKNOWN]"
            print(f"   {flag} {e['name']}{known}  args={json.dumps(e['args'], ensure_ascii=False)[:140]}")
            print(f"       -> {e['preview']}")
        print("  --- final answer ---")
        print("   " + r['final'].replace("\n", "\n   ")[:2200])
    print("\n" + "=" * 78)


async def main():
    query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY
    models = sys.argv[2:] if len(sys.argv) > 2 else DEFAULT_MODELS
    async with sse_client(SSE_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            valid = {t.name for t in tools}
            ollama_tools = to_ollama_tools(tools)
            print(f"Connected. {len(tools)} tools: {sorted(valid)}")
            results = []
            for m in models:
                print(f"\n>>> running {m} ...", flush=True)
                results.append(await run_model(m, query, session, ollama_tools))
            print_report(query, valid, results)
            with open("scripts/ab_last_run.json", "w") as f:
                json.dump({"query": query, "tools": sorted(valid), "results": results},
                          f, indent=2, ensure_ascii=False)
            print("Full transcript written to scripts/ab_last_run.json")


if __name__ == "__main__":
    asyncio.run(main())
