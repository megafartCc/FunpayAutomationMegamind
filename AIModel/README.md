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
- The bot stores full chat history and keeps a rolling summary to stay within
  token limits. Tune with AI_CONTEXT_MESSAGES / AI_SUMMARY_* env vars.
- REQUIRE_PAID_ORDER=true ensures accounts are issued only after ORDER_PAID.
