# Deploying MockFlow-AI to a Google Cloud e2-micro (Always Free)

A single always-on VM, no recurring charge, on your own domain.

> **Do not tear down Fly until step 10.** If the box turns out to be too small,
> you want somewhere to fall back to. The teardown is the last step on purpose.

---

## Why this host

Of the free options actually checked in Sept 2026, GCP's `e2-micro` is the only
mainstream **always-free VM with no idle-reclaim clause**. Oracle's Always Free
A1 has better specs but reclaims instances whose 95th-percentile CPU **and**
network **and** memory are all under 20% over 7 days — which an idle interview
app trips on all three. Koyeb closed its free tier to new signups, Hugging Face
now requires a paid plan for Docker Spaces, and Render's free tier sleeps.

**The catch, stated plainly:** e2-micro has **1 GB of RAM**. The app idles at a
measured ~263 MB, and each interview adds an `agent_worker.py` subprocess loading
Silero VAD through onnxruntime — expected 300–400 MB, **not yet measured against
a live interview**. So one concurrent interview should fit and two will not.
`MAX_CONCURRENT_WORKERS=1` and a swap file are not optional here.

The other constraint that rules out most free hosts: during a 20–40 minute
interview the browser talks to **LiveKit Cloud**, not to this app — `interview.html`
makes zero `fetch()` calls. Anything that sleeps on "no HTTP traffic" kills the
agent mid-interview. A plain VM has no such behaviour, which is the point.

### Free-tier rules you must not break

| Rule | Why it matters |
|---|---|
| Region **must** be `us-west1`, `us-central1`, or `us-east1` | Anywhere else is billed at standard rates. |
| Machine type **must** be `e2-micro` | Anything larger is billed. |
| Network tier **must** be `STANDARD` | Premium tier bills egress from the first byte. |
| Boot disk **must** be `pd-standard`, ≤30 GB | Balanced/SSD disks are billed. |
| Keep the static IP **attached to a running instance** | A reserved IP that is unattached is billed. |

Egress beyond the free allowance is billed, but this app's traffic is small —
the audio goes through LiveKit, not through your VM.

---

## 0. Prerequisites

- A Google Cloud account with **billing enabled** (required even for Always Free;
  it is what proves you are not a bot). Set a **budget alert at $1** so any
  mistake is loud and early.
- `gcloud` CLI installed and authenticated: `gcloud auth login`
- A domain you control.
- Your existing `.env` — you will reuse two values from it, see step 5.

```bash
gcloud config set project YOUR_PROJECT_ID
```

---

## 1. Create the VM

```bash
gcloud compute instances create mockflow-ai --zone=us-central1-a --machine-type=e2-micro --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=30GB --boot-disk-type=pd-standard --network-interface=network-tier=STANDARD,subnet=default --tags=http-server,https-server
```

Every flag there is load-bearing for staying inside the free tier — see the table
above before changing any of them.

---

## 2. Pin the IP so it survives a reboot

An ephemeral IP changes when the instance stops, which would break your DNS.
Promote it to static:

```bash
gcloud compute instances describe mockflow-ai --zone=us-central1-a --format="get(networkInterfaces[0].accessConfigs[0].natIP)"
```

Take that address and reserve it:

```bash
gcloud compute addresses create mockflow-ip --region=us-central1 --network-tier=STANDARD --addresses=THE_IP_FROM_ABOVE
```

A reserved IP is free **while attached to a running instance**. If you later
delete the VM, release the address too or it starts billing.

---

## 3. Open the firewall

The default VPC usually has these already; creating them again is harmless.

```bash
gcloud compute firewall-rules create allow-http --allow=tcp:80 --target-tags=http-server --description="ACME challenge + redirect to HTTPS"
```

```bash
gcloud compute firewall-rules create allow-https --allow=tcp:443 --target-tags=https-server
```

**Leave port 80 open.** Caddy needs it for the Let's Encrypt challenge, and
closing it makes certificate renewal fail silently 90 days later.

---

## 4. Point DNS at it

At your DNS provider, create an **A record** for your domain (or a subdomain)
pointing at the reserved IP. Verify before continuing — Caddy cannot issue a
certificate until this resolves:

```bash
nslookup your-domain.com
```

---

## 5. Prepare the VM

SSH in:

```bash
gcloud compute ssh mockflow-ai --zone=us-central1-a
```

**Swap first.** 1 GB of RAM is not enough to build this image — pip installing
onnxruntime and the LiveKit stack will OOM without it.

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
```

Make it survive reboots:

```bash
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Install Docker:

```bash
curl -fsSL https://get.docker.com | sudo sh
```

```bash
sudo usermod -aG docker $USER && newgrp docker
```

Get the code:

```bash
git clone https://github.com/PranavMishra17/MockFlow-AI.git ~/MockFlow-AI
```

---

## 6. Put the secrets on the box

> ⚠️ **`ENCRYPTION_KEY` must be copied from your existing `.env`, not generated.**
> This VM points at the same Neon database, which currently holds **4 users'
> encrypted API keys**. A new Fernet key cannot decrypt them — those users lose
> their saved LiveKit/OpenAI/Deepgram keys silently, with no error, just failing
> interviews. Same for `SECRET_KEY` (a new one only logs everyone out).

Create the secrets file **outside the repo**, root-owned:

```bash
sudo mkdir -p /opt/mockflow && sudo touch /opt/mockflow/app.env && sudo chmod 600 /opt/mockflow/app.env
```

```bash
sudo nano /opt/mockflow/app.env
```

Paste these five, copying every value from your local `.env`:

```
DATABASE_URL=postgresql://...neon.tech/neondb?sslmode=require
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...
SECRET_KEY=...
ENCRYPTION_KEY=...
CORS_ORIGINS=https://your-domain.com
```

Note your local `.env` has the client secret under `GOOGLE_CLOUD_CLIENT_SECRET`.
The app accepts either name, but write it as `GOOGLE_CLIENT_SECRET` here.

Then tell Compose the domain:

```bash
cd ~/MockFlow-AI/deploy/gcp && echo "DOMAIN=your-domain.com" > .env
```

---

## 7. Register the callback with Google

**Skip this and sign-in is broken on arrival.** In Google Cloud Console →
Credentials → your OAuth client:

**Authorized redirect URIs** — the path is `/auth/google/callback`, not anything else:

```
https://your-domain.com/auth/google/callback
```

**Authorized JavaScript origins:**

```
https://your-domain.com
```

---

## 8. Build and start

The first build takes **10–20 minutes** on an e2-micro and will lean on the swap
file. That is expected; it is a one-off.

```bash
cd ~/MockFlow-AI/deploy/gcp && docker compose up -d --build
```

Watch it come up:

```bash
docker compose logs -f
```

`restart: always` plus Docker's own systemd unit means both containers come back
after a reboot, so nothing else is needed for always-on.

---

## 9. Verify

```bash
curl -fsS https://your-domain.com/health
```

You want `{"database":"reachable","status":"healthy","workers":{...}}`.

Then check headroom, because this is the number that decides whether e2-micro is
viable at all:

```bash
free -m
```

**Then run a real interview.** Sign in, add keys in Settings, and do one intro
track end to end. This is the only check that exercises the mic, VAD, TTS and the
data channel — none of which any automated test covers. While it runs, from a
second SSH session:

```bash
free -m
```

If `available` drops near zero or the interview audio breaks up, e2-micro is too
small and you should fall back to Fly (which is still up — that is why step 10
comes last).

---

## 10. Only now, sunset Fly

Once a real interview has completed on the new host:

```bash
fly apps destroy mockflow-ai
```

Then clean up the leftovers:

- Delete the `RENDER_URL` and `APP_URL` repo variables, or repoint `APP_URL` at
  the new domain so the keep-warm workflow and the post-deploy health smoke stop
  pointing at dead hosts.
- Remove the `FLY_API_TOKEN` repo secret.
- Remove the old Fly and Render callback URLs from the Google OAuth client.
- `.github/workflows/deploy.yml` deploys via `flyctl`; it will skip harmlessly
  once the token is gone, but it is worth rewriting for the new host or deleting
  the deploy job.

---

## Troubleshooting

**Container restart-loops immediately.** Almost always a missing secret —
`FLASK_ENV=production` makes `app.py` fail fast at boot, and gunicorn exits 3
("worker failed to boot"). Check the env file first, not the logs:

```bash
docker compose exec web env | cut -d= -f1 | sort
```

**Certificate never issues.** Port 80 must be reachable and DNS must already
resolve to this VM. `docker compose logs caddy` names the actual ACME failure.

**Google sign-in fails with `redirect_uri_mismatch`.** The registered URI does
not match exactly. It must be `https://your-domain.com/auth/google/callback`.

**Interview audio breaks up / "inference slower than realtime".** e2-micro is a
shared-core burstable instance; sustained Silero VAD may exceed its baseline.
There is no free fix — this is the risk the guide opens with.

**Out of memory during build.** The swap file in step 5 is missing or too small.
`swapon --show` to confirm it is active.

**App killed mid-interview.** Check `dmesg | grep -i oom`. If the worker was OOM
killed, e2-micro cannot host this workload.
