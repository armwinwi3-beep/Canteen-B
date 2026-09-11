# Deployment status

Frontend: https://canteen-f.vercel.app/
Vercel project: https://vercel.com/arm-2756/canteen-f
GitHub: https://github.com/armwinwi3-beep/Canteen-F (main, root vue-project)
Deployed frontend commit: b335a9c

Backend: https://canteen-customer-api.onrender.com
Render: https://dashboard.render.com/web/srv-dagbnm740ujc73c5e1f0
GitHub: https://github.com/armwinwi3-beep/Canteen-B (main)
Deployed backend commit: 661131b
Build: pip install -r requirements.txt
Start: uvicorn customer_app:app --host 0.0.0.0 --port $PORT
Plan: free, region singapore. Git auto-deploy enabled.

Verified: frontend rendered with LINE login button; backend health 200; missing/invalid tokens 401; frontend CORS preflight 200; other origin rejected.
Supabase secret was stored only in Render backend environment with explicit user authorization.

Pending: log in to LINE Developers, set LIFF endpoint to https://canteen-f.vercel.app/ and verify scopes openid/profile. Complete real LINE account login and verify saved customer. LIFF ID: 2010896662-9IK1fj4R. Channel ID: 2010896662.

Customer LIFF authentication is the deployed feature. Ordering and merchant website are still pending implementation.