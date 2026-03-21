from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
import json, re

def _extract_json(text):
    text = text.strip()
    if text.startswith("```json"): text = text[7:]
    elif text.startswith("```"): text = text[3:]
    if text.endswith("```"): text = text[:-3]
    try: return json.loads(text.strip())
    except json.JSONDecodeError:
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try: return json.loads(json_match.group())
            except Exception: pass
    return {}

llm = ChatOpenAI(base_url="http://127.0.0.1:8080/v1", api_key="sk-no-key", model="llama3", temperature=0.1, max_tokens=4000)

PROMPT = PromptTemplate(template="""You are the Analyst Agent (Stance Detection).
Analyze the following posts by a Bluesky user. The goal is to filter FALSE POSITIVES from the BERT model.
You must determine the user's STANCE regarding misogyny in each post.
Possible stances:
- PROMOTING (supports misogyny)
- DENOUNCING (denounces misogyny)
- QUOTING (quoting someone else to expose them)
- SARCASTIC (sarcasm mocking misogynists)

You MUST return ONLY a valid JSON object with the exact following structure:
{{
  "analyzed_posts": [
    {{
      "text": "original text of the post",
      "stance": "PROMOTING" | "DENOUNCING" | "QUOTING" | "SARCASTIC",
      "reason": "Brief explanation of why",
      "is_genuine_misogyny": true or false (true ONLY if PROMOTING)
    }}
  ]
}}

Posts to analyze:
- "regardless who is doing the behavior" except somehow never to men, and instead only to women, with a major focus on queer women, which is not suspicious at all. These bland excuses for misogyny are exhausting.
- "a lot of women like the gay dude stuff, therefore the gay women stuff must be for men" and then centering men exclusively is certainly male writer logic.
""", input_variables=[])

chain = PROMPT | llm | StrOutputParser()
raw = chain.invoke({})
print("RAW LLM OUTPUT:")
print(raw)
print("---")
res = _extract_json(raw)
print("EXTRACTED JSON:")
print(res)

