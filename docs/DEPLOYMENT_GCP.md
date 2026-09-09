# Deploying MockFlow-AI to a Google Cloud e2-micro (Always Free)

A single always-on VM, no recurring charge, on your own domain.

Written for someone who has **never used Google Cloud**. Every command that has a
placeholder in it says exactly where to get that value.

> **Do not tear down Fly until Part I.** If this box turns out to be too small,
> you want somewhere to fall back to. The teardown is the last step on purpose.

---

## The three values you will need

Fill these in as you go. Every `<PLACEHOLDER>` below is one of these.

| Placeholder | What it is | Where you get it |
|---|---|---|
| `<PROJECT_ID>` | Google Cloud project id — **not** the display name | Part A, step 3 |
| `<DOMAIN>` | the hostname you'll serve on | Part D — **a free DuckDNS subdomain is fine**, you do not need to buy a domain |
| `<VM_IP>` | the server's public address | Part C, step 3 |

Keep them in a scratch note. You will paste each several times.

---

## Why this host, and the one real risk

Of the free options checked in Sept 2026, GCP's `e2-micro` is the only mainstream
**always-free VM with no idle-reclaim clause**. (Oracle reclaims idle instances;
Koyeb closed its free tier to new signups; Hugging Face now needs a paid plan for
Docker Spaces; Render sleeps.)

**The risk, stated up front:** e2-micro has **1 GB of RAM**. The app idles at a
measured ~263 MB, and each interview adds a subprocess loading Silero VAD through
onnxruntime — expected 300–400 MB, but **never measured against a live
interview**. One concurrent interview should fit; two will not. Part H has you
watch memory during a real interview specifically to find out.

---

# Part A — Google Cloud account and project (browser)

### 1. Create the account

Go to **https://console.cloud.google.com** and sign in with your Google account.

If it's your first time it will offer a free trial with credit. Accept it. **You
must add a card even for the Always Free tier** — it's anti-abuse, not a charge.
Always Free resources keep working after the trial credit expires.

### 2. Create a project

Go to **https://console.cloud.google.com/projectcreate**

- **Project name:** `mockflow-ai` (anything you like)
- Click **CREATE**, wait ~10 seconds

### 3. Find your PROJECT_ID ← this is the thing you asked about

The project **ID** is not necessarily the name you typed. IDs must be globally
unique, so if your chosen name is already taken Google appends digits — you get
`mockflow-ai-473915` rather than `mockflow-ai`. If the name was free, the ID is
just the name. **Check rather than assume**, because every later command uses it.

Three places to see it:

- **Easiest:** the project dropdown at the top of the console. Click it — the
  table lists **Name** and **ID** side by side. Copy the **ID** column.
- Or the dashboard at **https://console.cloud.google.com/home/dashboard** —
  the "Project info" card shows **Project ID**.
- Or, after Part B, run: `gcloud projects list`

Write it down as `<PROJECT_ID>`.

### 4. Set a budget alert (do not skip)

This is your safety net against an accidental charge.

Go to **https://console.cloud.google.com/billing** → click your billing account →
**Budgets & alerts** in the left menu → **CREATE BUDGET**.

- **Name:** `alert-1-dollar`
- **Target amount:** `1` (USD)
- Leave the default thresholds (50%, 90%, 100%)
- **FINISH**

You'll now get an email if anything ever starts costing money.

### 5. Turn on Compute Engine

Go to **https://console.cloud.google.com/compute/instances** and click
**ENABLE** if prompted. First-time enablement takes a minute or two.

---

# Part B — Install the gcloud CLI (your Windows machine)

Download and run the installer:
**https://cloud.google.com/sdk/docs/install** → "Google Cloud CLI installer" for
Windows.

Accept the defaults, and leave **"Start Google Cloud SDK Shell"** and **"Run
gcloud init"** ticked at the end.

Then **open a new terminal** (the installer changes your PATH; an already-open
one won't see it) and check:

```bash
gcloud version
```

Sign in — this opens a browser:

```bash
gcloud auth login
```

> ### ⚠️ PowerShell users: quote every comma
>
> PowerShell turns an unquoted comma-separated argument into an **array** and
> passes it to gcloud joined by a space. `--tags=http-server,https-server` arrives
> as one tag called `http-server https-server`, and gcloud rejects it with a
> confusing regex error. Anything containing a comma must be quoted:
>
> `--tags="http-server,https-server"` ✅ &nbsp;&nbsp; `--tags=http-server,https-server` ❌
>
> Every command below is already written correctly. This is also why the
> `--network-interface=network-tier=STANDARD,subnet=default` form fails — the
> guide uses separate top-level `--network-tier` and `--subnet` flags instead.

Now point the CLI at your project. **Replace `<PROJECT_ID>` with the ID from Part
A step 3:**

```bash
gcloud config set project <PROJECT_ID>
```

Confirm it took:

```bash
gcloud config list
```

You should see your project id under `[core]`.

---

# Part C — Create the server

### 1. Create the VM

Paste this exactly. Every flag is load-bearing for staying free — see the table
in Part J before changing any of them.

```bash
gcloud compute instances create mockflow-ai --zone=us-central1-a --machine-type=e2-micro --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=30GB --boot-disk-type=pd-standard --network-tier=STANDARD --subnet=default --tags="http-server,https-server"
```

Takes about 30 seconds. It prints a table — the `EXTERNAL_IP` column is your
`<VM_IP>`.

**Two warnings here are expected and harmless:** one about the disk being under
200 GB (I/O performance, irrelevant at this scale), and one about the 30 GB disk
being larger than the 10 GB image (Debian resizes its root partition itself).

### 2. Open the firewall

The default network usually has these; running them again is harmless and the
error if they exist is safe to ignore.

```bash
gcloud compute firewall-rules create allow-http --allow=tcp:80 --target-tags="http-server"
```

```bash
gcloud compute firewall-rules create allow-https --allow=tcp:443 --target-tags="https-server"
```

**Leave port 80 open.** The certificate system needs it, and closing it makes
renewal fail silently in 90 days.

### 3. Pin the IP so a reboot doesn't change it

Print the current address:

```bash
gcloud compute instances describe mockflow-ai --zone=us-central1-a --format="get(networkInterfaces[0].accessConfigs[0].natIP)"
```

That is your `<VM_IP>`. Now reserve it — **replace `<VM_IP>`**:

```bash
gcloud compute addresses create mockflow-ip --region=us-central1 --network-tier=STANDARD --addresses=<VM_IP>
```

A reserved IP is free **while attached to a running instance**. If you ever
delete the VM, release this address too or it starts billing.

---

# Part D — Get a hostname and point it at the server

You need a **hostname**, not just the IP. This is not optional and not cosmetic:
Google OAuth **refuses raw IP addresses** as redirect URIs (only `localhost` is
exempt) and **requires HTTPS**. Without a hostname, sign-in cannot work at all.

You do **not** have to buy one.

## Option 1 — A free subdomain from DuckDNS (recommended)

Free, permanent, no card, and it works with Let's Encrypt.

### D1. Claim the subdomain

1. Go to **https://www.duckdns.org** and sign in with Google/GitHub (no signup form).
2. In the **domains** box type the name you want, e.g. `mockflow-ai`, and click
   **add domain**.
3. Your hostname is now `mockflow-ai.duckdns.org`. That is your `<DOMAIN>`.

### D2. ⚠️ Test that Google accepts it — do this BEFORE any server work

This is the one thing that could sink the whole approach, and it takes a minute
to check. Google rejects some domains with *"must end with a public top-level
domain"* or *"must use a domain that is a valid top private domain"*.

Go to **https://console.cloud.google.com/apis/credentials** → your OAuth client →
**Authorized redirect URIs** → **ADD URI**, and paste:

```
https://<DOMAIN>/auth/google/callback
```

- **It saves cleanly** → you're fine, continue. (You've now also completed Part G.)
- **It refuses the domain** → stop and use Option 3 below instead. Don't build the
  server around a hostname that can't authenticate.

While you're here, add `https://<DOMAIN>` under **Authorized JavaScript origins**.

### D3. Point it at the VM

In the DuckDNS **current ip** box for your domain, paste `<VM_IP>` and click
**update ip**.

Your GCP address is *reserved* (Part C step 3), so it will not change — you do
**not** need DuckDNS's update client or a cron job. Set it once and forget it.

## Option 2 — A domain you already own

At your registrar's **DNS settings**, add:

| Field | Value |
|---|---|
| Type | `A` |
| Name / Host | `@` for the root domain, or e.g. `app` for `app.yourdomain.com` |
| Value / Points to | `<VM_IP>` |
| TTL | leave default |

## Option 3 — If Google rejected the DuckDNS name

Try, in order:

1. **deSEC** — https://desec.io — free, non-profit, gives you `yourname.dedyn.io`.
   A more conventional DNS host than DuckDNS, with a proper records UI.
   Set the record at **https://desec.io/domains** → your domain → add record:
   type `A`, **subname** (see below), records `<VM_IP>`, TTL `3600`.
2. **afraid.org FreeDNS** — https://freedns.afraid.org — free subdomains across
   many shared domains, so if one parent domain is rejected you can pick another.
   Note that on the free tier other people can also create names under the same
   shared domain.
3. **A cheap real domain** — a `.xyz` or `.top` is often a couple of dollars for
   the first year, and removes this whole class of problem permanently.

Re-run the D2 test with each candidate before building on it.

## Use a SUBDOMAIN, so one free domain serves every project

Do not dedicate the whole hostname to this app, and do not try to serve it under a
path like `yourname.dedyn.io/mockflow`.

**Use a subname.** Set the DNS record with subname `mockflow`, giving
`mockflow.yourname.dedyn.io`, and your bare domain stays free for other projects
(`blog.yourname.dedyn.io`, `api.yourname.dedyn.io`, …). Caddy routes by hostname,
so each project is independent. `<DOMAIN>` in this guide then means the full
subdomain.

**Why not a path prefix:** the app has **122 root-absolute URLs** — 101 `href`/`src`
attributes in templates and 21 `fetch()` calls — plus `url_for()` calls that
generate root-relative paths. Serving under `/mockflow` breaks every one of them
unless you rewrite them all and plumb `SCRIPT_NAME` through Flask. A subdomain
costs zero code changes. Measured, not guessed.

Subdomains of a valid registrable domain are fine for Google OAuth, so
`mockflow.yourname.dedyn.io` passes the D2 test the same way the bare name would.

## Verify DNS resolves — required before Part H

```bash
nslookup <DOMAIN>
```

**It must print `<VM_IP>` before you continue.** Caddy cannot obtain a
certificate until the name resolves publicly to this server, and Part H will fail
if you rush it. DNS changes usually take a few minutes; DuckDNS is near-instant.

---

# Part E — Set up the server

Connect. The first run generates an SSH key and may ask for a passphrase — you
can press Enter twice for none.

```bash
gcloud compute ssh mockflow-ai --zone=us-central1-a
```

Your prompt changes to something like `pranav@mockflow-ai:~$`. **Everything in
Parts E–H runs on the server, not your PC.**

### 1. Swap file — required, not optional

1 GB of RAM cannot build this image; pip installing onnxruntime will run out of
memory without swap.

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
```

Make it survive reboots:

```bash
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Confirm it's active:

```bash
swapon --show
```

You should see `/swapfile  file  2G`.

### 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
```

```bash
sudo usermod -aG docker $USER && newgrp docker
```

Check it works without sudo:

```bash
docker ps
```

### 3. Get the code

```bash
git clone https://github.com/PranavMishra17/MockFlow-AI.git ~/MockFlow-AI
```

---

# Part F — Put the secrets on the server

> ⚠️ **Copy `ENCRYPTION_KEY` from your existing `.env`. Do not generate a new one.**
> This VM points at the same Neon database, which holds **4 users' encrypted API
> keys**. A new key cannot decrypt them — those users would silently lose their
> saved LiveKit/OpenAI/Deepgram keys, with no error, just failing interviews.
> Same for `SECRET_KEY` (a new one only logs everyone out, which is survivable).

**On your Windows machine**, open `E:\MockFlow-AI\.env` in an editor and keep it
open — you're about to copy five values out of it.

**Back on the server**, create the secrets file outside the repo:

```bash
sudo mkdir -p /opt/mockflow && sudo touch /opt/mockflow/app.env && sudo chmod 600 /opt/mockflow/app.env
```

```bash
sudo nano /opt/mockflow/app.env
```

Type this in, pasting each value from your local `.env`. **Replace `<DOMAIN>`:**

```
DATABASE_URL=<paste DATABASE_URL from .env>
GOOGLE_CLIENT_ID=<paste GOOGLE_CLIENT_ID from .env>
GOOGLE_CLIENT_SECRET=<paste GOOGLE_CLOUD_CLIENT_SECRET from .env>
SECRET_KEY=<paste SECRET_KEY from .env>
ENCRYPTION_KEY=<paste ENCRYPTION_KEY from .env>
CORS_ORIGINS=https://<DOMAIN>
```

Note the third line: your `.env` stores the client secret under
`GOOGLE_CLOUD_CLIENT_SECRET`, but write it here as `GOOGLE_CLIENT_SECRET`.

Save and exit nano: **Ctrl+O**, **Enter**, **Ctrl+X**.

Then tell Docker Compose your domain — **replace `<DOMAIN>`**:

```bash
cd ~/MockFlow-AI/deploy/gcp && echo "DOMAIN=<DOMAIN>" > .env
```

---

# Part G — Register the callback with Google

**Skip this and sign-in is broken the moment the site comes up.**

> If you already added both URIs during the Part D2 acceptance test, this part is
> done — skip to Part H.

Go to **https://console.cloud.google.com/apis/credentials** and click your
existing OAuth 2.0 Client ID (the same one the app already uses).

Under **Authorized redirect URIs** → **ADD URI** — the path is
`/auth/google/callback`, exactly:

```
https://<DOMAIN>/auth/google/callback
```

Under **Authorized JavaScript origins** → **ADD URI**:

```
https://<DOMAIN>
```

Click **SAVE**. Changes can take a few minutes to propagate.

---

# Part H — Build, start, verify

Back on the server:

```bash
cd ~/MockFlow-AI/deploy/gcp && docker compose up -d --build
```

**The first build takes 10–20 minutes** on this small machine and leans hard on
the swap file. That's expected and only happens once. Watch it:

```bash
docker compose logs -f
```

Press **Ctrl+C** to stop watching (that does not stop the containers).

### Verify the site is up

From your own machine — **replace `<DOMAIN>`**:

```bash
curl -fsS https://<DOMAIN>/health
```

You want `{"database":"reachable","status":"healthy","workers":{...}}`.

### Check memory headroom

On the server:

```bash
free -m
```

### Then run a real interview — this is the actual test

Open `https://<DOMAIN>` in a browser, sign in with Google, add your API keys in
Settings, and do **one intro-track interview end to end**.

This is the only check that exercises the microphone, voice detection,
text-to-speech and the live data channel. No automated test covers any of it.

While the interview runs, open a **second** terminal and watch memory:

```bash
gcloud compute ssh mockflow-ai --zone=us-central1-a --command="free -m"
```

**If `available` drops near zero, or the audio breaks up, e2-micro is too small.**
Fly is still running — go to Part J and pick a fallback instead of Part I.

---

# Part I — Only now, sunset Fly

Once a real interview has completed successfully on the new host:

```bash
fly apps destroy mockflow-ai
```

Then clean up what points at dead hosts:

- In GitHub → Settings → Secrets and variables → Actions: delete the
  `FLY_API_TOKEN` secret, delete `RENDER_URL`, and set `APP_URL` to
  `https://<DOMAIN>`.
- In Google Cloud → Credentials → your OAuth client: remove the old
  `*.fly.dev` and `*.onrender.com` redirect URIs.
- `.github/workflows/deploy.yml` still deploys via `flyctl`. With the token gone
  it skips harmlessly, but it's worth rewriting for this host or deleting the
  deploy job.

---

# Part J — Reference

### Free-tier rules you must not break

| Rule | Why |
|---|---|
| Region must be `us-west1`, `us-central1`, or `us-east1` | Anywhere else bills at standard rates |
| Machine type must be `e2-micro` | Anything larger is billed |
| Network tier must be `STANDARD` | Premium bills egress from the first byte |
| Boot disk must be `pd-standard`, ≤30 GB | Balanced/SSD disks are billed |
| Keep the static IP attached to a running instance | An unattached reserved IP is billed |

### Everyday commands

Restart the app after pulling new code:

```bash
cd ~/MockFlow-AI && git pull && cd deploy/gcp && docker compose up -d --build
```

See what's running / read logs:

```bash
cd ~/MockFlow-AI/deploy/gcp && docker compose ps && docker compose logs --tail=50
```

### Troubleshooting

**Container restarts in a loop.** Almost always a missing secret —
`FLASK_ENV=production` makes the app fail fast at boot and gunicorn exits 3
("worker failed to boot"). Check which variables actually arrived:

```bash
docker compose exec web env | cut -d= -f1 | sort
```

**Certificate never issues / site shows a TLS warning.** Port 80 must be open and
DNS must already resolve to this VM. `docker compose logs caddy` names the real
failure.

**Google sign-in fails with `redirect_uri_mismatch`.** The URI in Part G doesn't
match exactly. It must be `https://<DOMAIN>/auth/google/callback` — not
`/api/auth/callback`, not with a trailing slash.

**Audio breaks up mid-interview.** e2-micro is a shared-core burstable instance
and sustained voice detection may exceed its baseline CPU. There is no free fix;
this is the risk the guide opens with.

**Build fails with "killed" or out-of-memory.** The swap file is missing.
`swapon --show` — if it prints nothing, redo Part E step 1.

**App dies mid-interview.** Check `dmesg | grep -i oom`. If the worker was
OOM-killed, e2-micro cannot host this workload.

### If e2-micro doesn't work out

In order of preference:

1. **Cloudflare Tunnel on your own machine** — genuinely free, full CPU, custom
   domain, no reclaim policy. Cost is leaving your PC on.
2. **Fly with scale-to-zero + a keepalive ping** during interviews — bills close
   to nothing, needs a small code change, ~20 minutes of work.
