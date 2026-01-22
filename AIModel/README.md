AIModel

This folder contains a minimal AI responder that can talk to users and trigger
safe actions (send account details or Steam codes) after payment is confirmed.

Groq setup (hosted, free tier available):
1) Get a Groq API key.
2) Set env vars in .env:
   AI_ENABLED=true
   AI_PROVIDER=groq
   AI_BASE_URL=https://api.groq.com/openai/v1
   AI_API_KEY=your_key
   AI_MODEL=llama-3.1-8b-instant

Notes:
- AI replies are in Russian (casual tone) per the system prompt.
- Actions are gated by active rentals; if there is no active rental, the bot
  will not send accounts or codes. Extend/cancel/stock are safe actions and
  still validate inputs on the server.
- The bot stores chat history and memory facts locally in AI_MEMORY_DIR
  (default: data/chat_memory) and keeps a rolling summary to stay within token
  limits. To share memory across instances, set AI_MEMORY_BACKEND=mysql so it
  uses the database with per-user isolation (user_id + owner). Tune with
  AI_CONTEXT_MESSAGES / AI_SUMMARY_* / AI_MEMORY_* env vars.
- Users can say "remember this - ..." and later ask "what do you remember".
- AI metrics are recorded to AI_METRICS_PATH (default: data/ai_metrics.json).
  View live metrics at /ai-dashboard (or /static/ai-dashboard.html).
- AI_ERROR_BUDGET_TARGET sets the allowed error-rate budget for the dashboard.
- A/B prompt support: set AI_SYSTEM_PROMPT_VARIANTS to a JSON list or use
  "prompt A|||prompt B" to split traffic by user hash.
- Backpressure: AI_MAX_CONCURRENT limits concurrent calls and
  AI_QUEUE_TIMEOUT_SECONDS controls wait time. AI_RATE_LIMIT_SECONDS throttles
  per-user requests.
- Live eval suite: run `AI_EVAL_LIVE=1 python -m unittest tests.test_ai_eval` to
  execute golden cases from `tests/ai_eval_cases.json` against your model.
- REQUIRE_PAID_ORDER=true ensures accounts are issued only after ORDER_PAID.
