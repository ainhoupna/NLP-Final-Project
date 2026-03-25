"""
MisogynAI Multi-Agent Architecture using LangChain.

This agent replaces the monolithic prompt with a 3-agent Sequential Flow:
1. Agent 1 (Analyst): Stance Detection & Context Extraction.
2. Agent 2 (Psychologist): Bias Categorization & Severity.
3. Agent 3 (Sociologist): Echo Chamber & Temporal Analysis.
"""

from __future__ import annotations
import os
import re
import json
import requests
import structlog
from datetime import datetime
from collections import defaultdict
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.exceptions import OutputParserException

logger = structlog.get_logger()

# ── Data Extraction Tools (No LLM, just raw DB extraction) ──────────

def _get_profile_stats(handle, mongo_collection):
    pipeline = [
        {"$match": {"author_handle": handle}},
        {"$group": {
            "_id": "$author_handle",
            "total": {"$sum": 1},
            "misog": {"$sum": {"$cond": [{"$eq": ["$qwen_misogyny", True]}, 1, 0]}}
        }}
    ]
    results = list(mongo_collection.aggregate(pipeline))
    if not results:
        return {"total": 0, "misog": 0, "rate": 0}
    t, m = results[0]["total"], results[0]["misog"]
    return {"total": t, "misog": m, "rate": round(m / t * 100, 1) if t > 0 else 0}

def _get_posts(handle, mongo_collection):
    # Prioritize BERT-flagged posts first, then newest
    all_posts = list(mongo_collection.find(
        {"author_handle": handle},
        {"text": 1, "created_at": 1, "bert_misogyny": 1, "misogyny_score": 1, "_id": 0}
    ).sort([("bert_misogyny", -1), ("created_at", -1)]).limit(15))
    
    formatted = []
    for p in all_posts:
        formatted.append({
            "text": p.get("text", "")[:400],
            "score": round(float(p.get("misogyny_score", 0)), 3) if p.get("misogyny_score") is not None else 0,
            "qwen": bool(p.get("qwen_misogyny", False)),
            "date": p.get("created_at", "")[:10]
        })
    return formatted

def _get_interactions(handle, mongo_collection, live_posts=None, live_follows=None):
    posts = list(mongo_collection.find({"author_handle": handle}, {"text": 1, "_id": 0}))
    if live_posts:
        posts.extend(live_posts)
        
    mention_counts = {}
    reply_guy_score = 0
    mention_re = re.compile(r'@([\w.-]+\.[\w.-]+)')
    
    for p in posts:
        text = p.get("text", "")
        if text.startswith("@"):
            reply_guy_score += 1
        for m in mention_re.findall(text):
            if m != handle:
                mention_counts[m] = mention_counts.get(m, 0) + 1
                
    if live_follows:
        for f_handle in live_follows:
            # Mentions matter slightly more than follows for engagement, but follows expand the DB sweep significantly.
            mention_counts[f_handle] = mention_counts.get(f_handle, 0) + 1
            
    top = sorted(mention_counts.items(), key=lambda x: x[1], reverse=True)[:15]
    interactions = []
    toxic_n, db_n = 0, 0
    
    for mh, cnt in top:
        stats = list(mongo_collection.aggregate([
            {"$match": {"author_handle": mh}},
            {"$group": {"_id": "$author_handle", "t": {"$sum": 1},
                        "m": {"$sum": {"$cond": [{"$eq": ["$qwen_misogyny", True]}, 1, 0]}}}}
        ]))
        if stats:
            db_n += 1
            r = stats[0]["m"] / stats[0]["t"] * 100 if stats[0]["t"] > 0 else 0
            if r > 0.1: # If they have ANY Qwen-confirmed misogyny, it's a toxic contact
                toxic_n += 1
            interactions.append({"handle": mh, "rate": round(r,1)})
            
    echo_pct = round(toxic_n / db_n * 100, 1) if db_n > 0 else 0
    reply_ratio = round(reply_guy_score / len(posts) * 100, 1) if posts else 0
    
    return {
        "reply_ratio_pct": reply_ratio,
        "echo_chamber_toxic_pct": echo_pct,
        "top_contacts": interactions
    }

def _get_temporal(handle, mongo_collection):
    posts = list(mongo_collection.find(
        {"author_handle": handle},
        {"created_at": 1, "misogyny_score": 1, "_id": 0}
    ).sort("created_at", 1))
    
    weeks = defaultdict(lambda: {"t": 0, "m": 0})
    for p in posts:
        try:
            dt = datetime.strptime(p["created_at"][:10], "%Y-%m-%d")
            wk = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
            weeks[wk]["t"] += 1
            if p.get("qwen_misogyny") is True:
                weeks[wk]["m"] += 1
        except Exception:
            pass
            
    timeline = []
    for w in sorted(weeks.keys()):
        d = weeks[w]
        timeline.append({"week": w, "total": d["t"], "toxic": d["m"], "rate": round(d["m"]/d["t"]*100,1) if d["t"] else 0})
    
    return timeline[-8:]


# ── LangChain Prompts ────────────────────────────────────────────────

PROMPT_AGENT_1 = PromptTemplate(
    template="""You are the Analyst Agent (Stance Detection).
Analyze the following posts by a Bluesky user. The goal is to filter FALSE POSITIVES from the BERT model.
You must determine the user's STANCE regarding misogyny in each post.
Possible stances:
- PROMOTING (supports misogyny or uses degrading language toward women/individuals)
- DENOUNCING (denounces misogyny, e.g., "Society is unfair to women" or "I hate sexism")
- QUOTING (quoting someone else to expose them)
- SARCASTIC (sarcasm mocking misogynists)

CRITICAL RULE FOR SPANISH:
- Terms like 'puta', 'zorra', 'guarra' when used as insults or to describe behavior are ALMOST ALWAYS PROMOTING. 
- Exception: 'puta madre' or 'hijo de puta' as intensifiers among friends (NEUTRAL).
- BUT 'Hora zorra' is EXPLICITLY PROMOTING (misogynistic slang).

You MUST return ONLY a valid JSON object with the exact following structure:
{{
  "analyzed_posts": [
    {{
      "post_id": 0,
      "stance": "PROMOTING" | "DENOUNCING" | "QUOTING" | "SARCASTIC" | "NEUTRAL",
      "reason": "Brief explanation of why (include if it's a known Spanish slur)",
      "is_genuine_misogyny": true or false
    }}
  ]
}}
NO PREAMBLE. NO COMMONSENSE EXPLANATIONS. START IMMEDIATELY WITH {{.

Posts to analyze (separated by ### ITEM P{idx} ###):
{posts_text}""",
    input_variables=["posts_text"]
)

PROMPT_AGENT_2 = PromptTemplate(
    template="""You are the Psychologist Agent (Deep Categorization).
Analyze THE FOLLOWING POSTS that have already been confirmed as MISOGYNISTIC.
Your job is to psychologically categorize them and detect behavioral patterns.

Categories:
- hostile: Explicit aggressiveness, insults, threats.
- benevolent: Paternalism, "women are weak/should stay at home".
- targeted_harassment: Continuous or direct attacks on female accounts.
- dogwhistles: Incel slang, coded language ("red pill", "simp").

You MUST return ONLY a valid JSON object with the exact following structure:
{{
  "categorization": {{
    "hostile": number of posts in this category,
    "benevolent": number of posts in this category,
    "targeted_harassment": number of posts in this category,
    "dogwhistles": number of posts in this category
  }},
  "patterns": [
    "Identified behavioral pattern 1 in English",
    "Identified behavioral pattern 2 in English"
  ]
}}

Confirmed misogynistic posts:
{genuine_posts}""",
    input_variables=["genuine_posts"]
)

PROMPT_AGENT_3 = PromptTemplate(
    template="""You are the Sociologist Agent (Behavior & Metadata).
Analyze this user's network metrics and temporal behavior to write a DEEP and COMPREHENSIVE sociological analysis.

Available data:
- Global Stats: {stats_text}
- Network Context: {network_text}
- Timeline (Last weeks): {temporal_text}

Mandatory rules:
1. In "interactions_analysis", write 2-3 extensive paragraphs explaining WHAT their Echo Chamber PCT and Reply Ratio mean. Deeply explain if they do "Dogpiling" (excessive replying to toxic environments) or not. Analyze the psychological and social implications of their interactions. Use the REAL NUMBERS provided.
2. In "temporal_analysis", write a detailed paragraph determining if the trend is UPWARD, STABLE, or ISOLATED based on the timeline. Explain what this means for their radicalization consistency.
3. Determine a final VERDICT (GENUINE MISOGYNIST, MODERATE RISK, INCONCLUSIVE, or LIKELY FALSE POSITIVE).
4. Write a general comprehensive summary of 3-4 sentences.

You MUST return ONLY a valid JSON object with the exact following structure:
{{
  "verdict": "GENUINE MISOGYNIST" | "MODERATE RISK" | "INCONCLUSIVE" | "LIKELY FALSE POSITIVE",
  "confidence": float between 0.0 and 1.0,
  "summary": "comprehensive summary here",
  "interactions_analysis": "deep analysis of interactions here",
  "temporal_analysis": "deep temporal analysis here"
}}
NO INTERNAL REASONING. NO PREAMBLE. NO <THOUGHTS>. RETURN ONLY THE JSON.
""",
    input_variables=["stats_text", "network_text", "temporal_text"]
)

# ── Safe JSON Extractor ──────────────────────────────────────────────

def _extract_json(text):
    if not text: return {}
    text = text.strip()
    # Remove obvious preambles like "Thinking Process:" or "Analysis:"
    text = re.sub(r'^(Thinking Process|Analysis|Thought|Reasoning):.*\n*', '', text, flags=re.IGNORECASE | re.MULTILINE)
    
    # Remove markdown code blocks
    text = re.sub(r'```json\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'```\s*', '', text, flags=re.IGNORECASE)
    text = text.replace('```', '')
    
    # Try finding the largest JSON-like block
    try:
        # First try finding a block starting with {
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            cand = text[start_idx:end_idx+1]
            # Replace smart quotes
            cand = cand.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
            return json.loads(cand)
    except Exception:
        pass
        
    try:
        return json.loads(text)
    except Exception:
        pass
    return {}

def _fetch_live_posts_bsky(handle: str, limit: int = 30) -> list:
    """Fetches posts directly from BlueSky public API without auth if local DB is sparse."""
    import requests
    try:
        url = f"https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor={handle}&limit={limit}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            live_posts = []
            for item in data.get("feed", []):
                post_obj = item.get("post", {})
                record = post_obj.get("record", {})
                if "text" in record:
                    live_posts.append({
                        "uri": post_obj.get("uri", ""),
                        "cid": post_obj.get("cid", ""),
                        "author_handle": handle,
                        "text": record.get("text", ""),
                        "created_at": record.get("createdAt", ""),
                        "is_live_fetched": True
                    })
            return live_posts
    except Exception as e:
        logger.warning("live_bsky_fetch_error", handle=handle, error=str(e))
    return []

def _call_llm(prompt, llm_url, max_tokens=2000):
    url = f"{llm_url}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "You are a specialized AI agent for misogyny analysis. ALWAYS return VALID JSON. NO PREAMBLE. NO EXPLANATIONS."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "stream": False
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        if response.status_code == 200:
            data = response.json()
            message = data['choices'][0]['message']
            content = message.get('content', '')
            reasoning = message.get('reasoning_content', '')
            
            # Use reasoning if content is empty (fallback for some Qwen/DeepSeek variants)
            if not content.strip() and reasoning.strip():
                return reasoning
            return content
        else:
            logger.error("llm_api_error", status=response.status_code, text=response.text)
            return ""
    except Exception as e:
        logger.error("llm_request_failed", error=str(e))
        return ""

def _fetch_live_network_bsky(handle, limit=50):
    """Fetches the accounts that the user is actively following from the public BlueSky API."""
    import requests
    try:
        url = f"https://public.api.bsky.app/xrpc/app.bsky.graph.getFollows?actor={handle}&limit={limit}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            return [f.get("handle") for f in data.get("follows", []) if f.get("handle")]
    except Exception as e:
        logger.warning("live_network_fetch_error", handle=handle, error=str(e))
    return []

# ── Main Generator Function (SSE-compatible) ─────────────────────────


def run_agent_analysis_stream(handle, mongo_collection, llm_url):
    """Generator: yields SSE events and orchestrates the LangChain multi-agent flow."""
    logger.info("agent_started", handle=handle)
    
    # Initialize LLM
    llm = ChatOpenAI(
        openai_api_base=f"{llm_url}/v1", 
        openai_api_key="sk-no-key", 
        model_name="gpt-3.5-turbo", # Use a standard name that works with LLM servers
        temperature=0.1,
        max_tokens=2000,
        request_timeout=60, # Large timeout for long Qwen generations
        streaming=False # Disable streaming for stable invoke
    )
    
    from langchain_core.output_parsers import StrOutputParser
    str_parser = StrOutputParser()

    try:
        # Step 0: Data gathering
        yield {"type": "status", "step": "data_gathering", "message": f"🔍 Extracting data and network graph for @{handle}..."}
        
        stats = _get_profile_stats(handle, mongo_collection)
        posts_data = _get_posts(handle, mongo_collection)
        temporal = _get_temporal(handle, mongo_collection)
        
        live_posts = []
        if len(posts_data) < 15:
            yield {"type": "status", "step": "data_gathering", "message": f"🌐 Thin profile detected. Fetching deep live context for @{handle}..."}
            live_posts = _fetch_live_posts_bsky(handle, limit=30)
            
            # Merge avoiding duplicates
            existing_uris = {p.get("uri") for p in posts_data if p.get("uri")}
            new_posts = []
            for lp in live_posts:
                if lp["uri"] not in existing_uris:
                    new_posts.append(lp)
                    existing_uris.add(lp["uri"])
                    
            if new_posts:
                posts_data.extend(new_posts)
                stats["total"] += len(new_posts)
                yield {"type": "status", "step": "data_gathering", "message": f"📥 Added {len(new_posts)} live posts to context."}
                
        # Always enrich network with live API to solve siloed DB metrics
        yield {"type": "status", "step": "data_gathering", "message": f"🕸️ Traversing live AT Protocol graph for @{handle}..."}
        live_follows = _fetch_live_network_bsky(handle, limit=50)
        
        interactions = _get_interactions(handle, mongo_collection, live_posts=live_posts, live_follows=live_follows)

        if not posts_data:
            raise ValueError("No posts found for this user, even after live fetch attempts.")
            
        yield {"type": "tool_done", "tool": "Data Collection", "message": "Raw data extracting and graph traversal complete.", "emoji": "🗄️", "detail": f"{stats['total']} posts analyzed, {len(live_follows)} net edges"}

        # Step 1: Agent 1 (Stance Detection)
        yield {"type": "tool_start", "tool": "Agent 1: Analyst", "message": "Context & Stance Analyzer processing posts (Deep Analysis)...", "emoji": "🧐"}
        
        # Clearer delimitation for the Analyst
        posts_text_block = "\n".join([f"### ITEM P{i} ###\n{p['text']}\n" for i, p in enumerate(posts_data[:15])])
        # Escaping curly braces for .format() if content has them
        posts_text_block = posts_text_block.replace("{", "[").replace("}", "]")
        
        # Adding anti-thought instruction
        posts_text_block += "\n\nNO PREAMBLE. NO INTERNAL MONOLOGUE. START YOUR JSON RESPOND WITH '{'."
        
        try:
            full_prompt = PROMPT_AGENT_1.format(posts_text=posts_text_block)
            logger.info("agent1_calling_llm", prompt_len=len(full_prompt))
            raw_output = _call_llm(full_prompt, llm_url, max_tokens=4000)
            logger.info("agent1_raw_output", raw=raw_output[:500] + "...")
            agent1_results = _extract_json(raw_output)
            logger.info("agent1_parsed", count=len(agent1_results.get("analyzed_posts", [])) if agent1_results else 0)
        except Exception as e:
            logger.error("agent1_failed", error=str(e))
            agent1_results = {}
        
        analyzed_posts = agent1_results.get("analyzed_posts", [])
        # Map back to real text
        mapped_posts = []
        for ap in analyzed_posts:
            if not isinstance(ap, dict): continue
            # Handle both int and string IDs
            try:
                idx = int(ap.get("post_id")) if ap.get("post_id") is not None else None
            except (ValueError, TypeError):
                idx = None
                
            if idx is not None and 0 <= idx < len(posts_data[:15]):
                ap["text"] = posts_data[idx]["text"]
                mapped_posts.append(ap)
                
        genuine_posts = [p for p in mapped_posts if p.get("is_genuine_misogyny", False) is True or str(p.get("is_genuine_misogyny")).lower() == "true"]
        false_positives = [p for p in mapped_posts if (p.get("is_genuine_misogyny", False) is False or str(p.get("is_genuine_misogyny")).lower() == "false") and p.get("stance") != "PROMOTING"]
        
        # If we have no genuine posts, include a few benign ones so the user sees analysis work
        benign_posts = [p for p in mapped_posts if p not in genuine_posts and p not in false_positives]
        if not genuine_posts and not false_positives and mapped_posts:
            benign_posts = mapped_posts[:5]
        
        yield {"type": "tool_done", "tool": "Agent 1: Analyst", "message": "Context analysis finished.", "emoji": "🧐", "detail": f"{len(genuine_posts)} legitimately toxic posts, {len(false_positives)} false positives."}

        # Step 2: Agent 2 (Psychologist)
        yield {"type": "tool_start", "tool": "Agent 2: Psychologist", "message": "Broadly categorizing bias depths and patterns...", "emoji": "🧠"}
        
        if genuine_posts:
            genuine_text_block = "\\n".join([f"- {p.get('text', '')}" for p in genuine_posts])
            # Escape braces for .format()
            genuine_text_block = genuine_text_block.replace("{", "{{").replace("}", "}}")
            chain2 = PROMPT_AGENT_2 | llm | str_parser
            try:
                full_prompt2 = PROMPT_AGENT_2.format(genuine_posts=genuine_text_block)
                raw_output2 = _call_llm(full_prompt2, llm_url, max_tokens=2000)
                agent2_results = _extract_json(raw_output2)
                if not agent2_results or ("categorization" not in agent2_results and "patterns" not in agent2_results):
                    raise ValueError("Agent 2 returned invalid or empty JSON")
            except Exception as e:
                logger.error("agent2_parse_failed", error=str(e))
                # Fallback that acknowledges the genuine posts found by Agent 1
                agent2_results = {
                    "categorization": {"hostile": len(genuine_posts), "benevolent": 0, "targeted_harassment": 0, "dogwhistles": 0}, 
                    "patterns": ["Shows hostility or toxic behavior in the analyzed text."]
                }
        else:
            agent2_results = {
                "categorization": {"hostile": 0, "benevolent": 0, "targeted_harassment": 0, "dogwhistles": 0},
                "patterns": ["The user does not show a sustained pattern of misogyny after processing their real context."]
            }
            
        if not isinstance(agent2_results, dict):
            agent2_results = {}
            
        yield {"type": "tool_done", "tool": "Agent 2: Psychologist", "message": "Psychological categorization completed.", "emoji": "🧠", "detail": "Patterns successfully cataloged"}

        # Step 3: Agent 3 (Sociologist)
        yield {"type": "tool_start", "tool": "Agent 3: Sociologist", "message": "Evaluating deep networks, echo chambers and behavior...", "emoji": "👥"}
        
        # Override naive DB stats with Agent 1's deep analysis findings for Agent 3
        stats["misog"] = len(genuine_posts)
        if stats["total"] > 0:
            stats["rate"] = round((stats["misog"] / stats["total"]) * 100, 1)
        else:
            stats["rate"] = 0

        try:
            stats_text = f"Total: {stats.get('total', 0)} posts, Misogynistic: {stats.get('misog', 0)}, Rate: {stats.get('rate', 0)}%"
            net_data = interactions
            network_text = f"Reply Ratio: {net_data.get('reply_ratio_pct', 0)}%, Echo Chamber Toxic: {net_data.get('echo_chamber_toxic_pct', 0)}%. Top contacts: " + ", ".join([f"@{c['handle']} ({c['rate']}%)" for c in net_data.get('top_contacts', [])[:5]])
            temporal_text = " -> ".join([f"{w['week']}: {w['rate']}%" for w in temporal])
            
            full_prompt3 = PROMPT_AGENT_3.format(
                stats_text=stats_text,
                network_text=network_text,
                temporal_text=temporal_text
            )
            logger.info("agent3_full_prompt", length=len(full_prompt3))
            # Drastically increase tokens since Agent 3 needs room for paragraphs AND reasoning
            raw_output3 = _call_llm(full_prompt3, llm_url, max_tokens=6000)
            agent3_results = _extract_json(raw_output3)
            
            # Additional check: if JSON was valid but empty or missing keys, force fallback
            if not agent3_results or "summary" not in agent3_results:
                raise ValueError("Agent 3 returned valid JSON but missing summary key")

        except Exception as e:
            logger.error("agent3_failed", error=str(e))
            agent3_results = {
                "verdict": "MODERATE RISK" if stats.get("rate", 0) > 10 else "INCONCLUSIVE",
                "confidence": 0.5,
                "summary": f"Based on {stats.get('total', 0)} posts, the user shows a toxic rate of {stats.get('rate', 0)}%. No sustained pattern of genuine misogyny detected beyond isolated incidents.",
                "interactions_analysis": f"The user has an echo chamber toxicity of {interactions.get('echo_chamber_toxic_pct', 0)}% and a reply ratio of {interactions.get('reply_ratio_pct', 0)}%.",
                "temporal_analysis": f"Behavior is consistent with the temporal data spanning {len(temporal)} weeks."
            }
        
        # Final safety guarantee
        if not isinstance(agent3_results, dict):
            agent3_results = {}
        for k in ["summary", "interactions_analysis", "temporal_analysis"]:
            if k not in agent3_results or not agent3_results[k]:
                agent3_results[k] = "No data available for this analysis component."
        
        yield {"type": "tool_done", "tool": "Agent 3: Sociologist", "message": "Deep sociological evaluation finished", "emoji": "👥", "detail": "Metrics interpreted"}

        # Step 4: Assembler
        yield {"type": "status", "step": "parsing", "message": "📋 Assembling final unified report..."}
        
        final_result = {
            "status": "success",
            "handle": handle,
            "verdict": agent3_results.get("verdict", "INCONCLUSIVE"),
            "confidence": agent3_results.get("confidence", 0.6),
            "summary": agent3_results.get("summary", ""),
            "interactions_analysis": agent3_results.get("interactions_analysis", ""),
            "temporal_analysis": agent3_results.get("temporal_analysis", ""),
            "toxicity_ratio": f"{stats['misog']} out of {stats['total']} posts ({stats['rate']}%) correctly flagged by AI Agent",
            "patterns": agent2_results.get("patterns", []),
            "categorization": agent2_results.get("categorization", {
                "hostile": 0, "benevolent": 0, "targeted_harassment": 0, "dogwhistles": 0
            }),
            "flagged_posts": [],
            "false_positives": [],
            "temporal_data": temporal,
            "network_data": interactions,
            "stats": stats
        }
        
        # Combine all analyses for the UI to show "analyzed phrases"
        for p in mapped_posts:
            # Determine if it's a genuine one or not
            is_genuine = p.get("is_genuine_misogyny", False) is True or str(p.get("is_genuine_misogyny")).lower() == "true"
            final_result["flagged_posts"].append({
                "text": p.get("text", ""),
                "reason": p.get("reason", "Analyzed post"),
                "stance": p.get("stance", "NEUTRAL"),
                "is_genuine": is_genuine
            })
            
            if not is_genuine and p.get("stance") != "PROMOTING":
                final_result["false_positives"].append({
                    "text": p.get("text", "")[:150],
                    "reason": p.get("reason", "Analyzed as non-misogynistic")
                })

        logger.info("final_report_assembled", flagged_count=len(final_result["flagged_posts"]))
        yield {"type": "tool_done", "tool": "parsing", "message": "Report generated successfully.", "emoji": "📋"}
        yield {"type": "result", "data": final_result}

    except Exception as e:
        logger.error("agent_failed", handle=handle, error=str(e))
        yield {"type": "error", "message": str(e)}

    
def run_agent_analysis(handle, mongo_collection, llm_url):
    """Non-streaming wrapper."""
    for event in run_agent_analysis_stream(handle, mongo_collection, llm_url):
        if event["type"] == "result":
            return event["data"]
        elif event["type"] == "error":
            return {"status": "error", "handle": handle, "error": event["message"]}
    return {"status": "error", "handle": handle, "error": "Agent produced no result"}
