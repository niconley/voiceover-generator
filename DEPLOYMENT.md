# Deployment Guide

Quick guide to deploy the Voiceover Generator for team access.

---

## Option 1: ngrok (Fastest - 5 minutes)

**Best for:** Temporary sharing, demos, testing

### Steps:

1. **Install ngrok:**
   ```bash
   brew install ngrok
   ```

2. **Make sure your server is running locally:**
   ```bash
   cd /Users/nicconley/Desktop/New\ Claude\ code\ project
   source venv/bin/activate
   export PATH="/opt/homebrew/bin:$PATH"
   FLASK_PORT=8080 python frontend/app.py
   ```

3. **In a new terminal, start ngrok:**
   ```bash
   ngrok http 8080
   ```

4. **Share the URL** (e.g., `https://abc123.ngrok-free.app`) with your team

**Pros:**
- ⚡ Instant (< 5 minutes)
- No deployment needed
- Free tier available

**Cons:**
- ⚠️ URL changes on restart
- Requires your computer to stay on
- Limited concurrent users on free tier

---

## Option 2: Railway (Easy Cloud Deploy - 10 minutes)

**Best for:** Permanent deployment, small teams

### Steps:

1. **Create Railway account:**
   - Go to [railway.app](https://railway.app)
   - Sign up with GitHub

2. **Deploy from GitHub:**
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose your `voiceover-generator` repository

3. **Set environment variables:**
   In Railway dashboard → Variables, add:
   ```
   ELEVENLABS_API_KEY=your_key_here
   ANTHROPIC_API_KEY=your_key_here
   GOOGLE_API_KEY=your_key_here
   ENABLE_LLM_QC=true
   ENABLE_AUDIO_QC=true
   WHISPER_MODEL=base
   ```

4. **Railway auto-deploys!** You'll get a URL like `https://voiceover-generator.up.railway.app`

**Pros:**
- ✅ Free tier: $5/month credit (enough for small teams)
- Automatic deployments on git push
- Permanent URL
- Easy to scale

**Cons:**
- Paid after free tier
- Cold starts (first request may be slow)

---

## Option 3: Heroku (Classic Option - 15 minutes)

**Best for:** Established teams, production use

### Steps:

1. **Install Heroku CLI:**
   ```bash
   brew tap heroku/brew && brew install heroku
   ```

2. **Login and create app:**
   ```bash
   cd /Users/nicconley/Desktop/New\ Claude\ code\ project
   heroku login
   heroku create voiceover-generator-yourteam
   ```

3. **Set environment variables:**
   ```bash
   heroku config:set ELEVENLABS_API_KEY=your_key_here
   heroku config:set ANTHROPIC_API_KEY=your_key_here
   heroku config:set GOOGLE_API_KEY=your_key_here
   heroku config:set ENABLE_LLM_QC=true
   heroku config:set ENABLE_AUDIO_QC=true
   heroku config:set WHISPER_MODEL=base
   ```

4. **Deploy:**
   ```bash
   git push heroku main
   ```

5. **Open app:**
   ```bash
   heroku open
   ```

**Pros:**
- Reliable and mature platform
- Good free tier
- Easy scaling
- Logs and monitoring

**Cons:**
- Free tier sleeps after 30 min inactivity
- Paid plans start at $7/month

---

## Option 4: DigitalOcean App Platform (Robust - 20 minutes)

**Best for:** Production, high traffic

### Steps:

1. **Create DigitalOcean account:**
   - Go to [digitalocean.com](https://www.digitalocean.com)
   - Sign up

2. **Deploy from GitHub:**
   - Go to Apps → Create App
   - Connect GitHub repository
   - Select `voiceover-generator`

3. **Configure:**
   - Runtime: Python
   - Build command: `pip install -r requirements.txt`
   - Run command: `python frontend/app.py`
   - Port: 8080

4. **Add environment variables** in the app settings

5. **Deploy!** You'll get a URL like `https://voiceover-generator-abc123.ondigitalocean.app`

**Pros:**
- Professional-grade infrastructure
- $5/month starter tier
- No cold starts
- Good performance

**Cons:**
- Paid from the start
- Slightly more complex setup

---

## Recommended Path

**For quick testing:**
→ Use **ngrok** (Option 1)

**For permanent team access:**
→ Use **Railway** (Option 2) - Best balance of ease and features

**For production:**
→ Use **DigitalOcean** (Option 4) - Most reliable

---

## After Deployment

### Share with your team:
1. Send them the deployment URL
2. Upload CSV template (in `input_templates/` folder)
3. Set expectations:
   - Each voiceover takes 30-60s to generate
   - 5 retry attempts for timing accuracy
   - Both Text QC and Audio QC will run

### Monitor usage:
- Check logs in your deployment platform
- Monitor API usage (ElevenLabs, Anthropic, Google)
- Set up alerts if needed

---

## Troubleshooting

### "Application Error" on Railway/Heroku
- Check environment variables are set correctly
- Review logs: `heroku logs --tail` or Railway dashboard
- Ensure all API keys are valid

### Slow performance
- Upgrade to paid tier for faster instances
- Consider reducing MAX_RETRIES in config
- Use smaller Whisper model (tiny instead of base)

### Out of API credits
- Check ElevenLabs character usage
- Monitor Anthropic API usage
- Google Gemini has generous free tier

---

## Security Notes

⚠️ **Important:**
- Never commit `.env` file to git (already in `.gitignore`)
- Rotate API keys regularly
- Consider adding basic authentication for team access
- Monitor for unusual usage patterns

---

Need help? Check the logs or reach out!
