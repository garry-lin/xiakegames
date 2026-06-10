#!/usr/bin/env python3
"""
Set Spaceship DNS for xiakegames.com -> Vercel.

Required env vars:
  SPACESHIP_API_KEY
  SPACESHIP_API_SECRET

Usage:
  python scripts/set_spaceship_dns.py --dry-run
  python scripts/set_spaceship_dns.py --apply
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DOMAIN = "xiakegames.com"
BASE = "https://spaceship.dev/api/v1"
TARGET_A = "76.76.21.21"
TARGET_WWW_CNAME = "cname.vercel-dns.com"
TTL = 3600


def headers():
    key = os.environ.get("SPACESHIP_API_KEY")
    secret = os.environ.get("SPACESHIP_API_SECRET")
    if not key or not secret:
        raise SystemExit(
            "Missing SPACESHIP_API_KEY / SPACESHIP_API_SECRET env vars.\n"
            "Do not paste secrets into chat; set them in your local terminal first."
        )
    return {
        "X-API-Key": key,
        "X-API-Secret": secret,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "xiakegames-dns-setup/1.0",
    }


def request(method, path, body=None):
    url = BASE + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, method=method, headers=headers(), data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", "replace")
            return r.status, text, dict(r.headers)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {e.code}\n{text}") from e


def get_records():
    status, text, _ = request("GET", f"/dns/records/{DOMAIN}?take=500&skip=0&orderBy=name")
    if status != 200:
        raise RuntimeError(f"GET records returned {status}: {text}")
    data = json.loads(text or "{}")
    return data.get("items", [])


def delete_records(records):
    if not records:
        return
    status, text, _ = request("DELETE", f"/dns/records/{DOMAIN}", records)
    if status != 204:
        raise RuntimeError(f"DELETE records returned {status}: {text}")


def put_records(records):
    payload = {"force": True, "items": records}
    status, text, _ = request("PUT", f"/dns/records/{DOMAIN}", payload)
    if status != 204:
        raise RuntimeError(f"PUT records returned {status}: {text}")


def norm_name(r):
    return str(r.get("name", "")).strip().lower()


def deletion_shape(r):
    t = r.get("type")
    name = r.get("name")
    out = {"type": t, "name": name}
    # Spaceship DELETE requires identifying fields by type.
    for k in [
        "address", "cname", "aliasName", "value", "exchange", "preference",
        "nameserver", "flag", "tag", "port", "scheme", "svcPriority",
        "targetName", "svcParams", "protocol", "usage", "selector",
        "matching", "associationData", "service", "weight", "target"
    ]:
        if k in r:
            out[k] = r[k]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually update Spaceship DNS")
    ap.add_argument("--dry-run", action="store_true", help="Show planned changes only")
    args = ap.parse_args()
    if not args.apply and not args.dry_run:
        args.dry_run = True

    records = get_records()
    print(f"Current custom records for {DOMAIN}: {len(records)}")
    for r in records:
        print(" -", json.dumps(r, ensure_ascii=False))

    to_delete = []
    for r in records:
        t = r.get("type")
        n = norm_name(r)
        # Remove conflicting parking/root/www records only. Preserve MX/TXT/NS/etc.
        if n == "@" and t in {"A", "ALIAS", "CNAME"}:
            # Replace apex with Vercel A record.
            if not (t == "A" and r.get("address") == TARGET_A):
                to_delete.append(deletion_shape(r))
        if n == "www" and t in {"A", "ALIAS", "CNAME"}:
            # Replace www with Vercel CNAME.
            if not (t == "CNAME" and r.get("cname") == TARGET_WWW_CNAME):
                to_delete.append(deletion_shape(r))

    desired = [
        {"type": "A", "name": "@", "address": TARGET_A, "ttl": TTL},
        {"type": "CNAME", "name": "www", "cname": TARGET_WWW_CNAME, "ttl": TTL},
    ]

    print("\nRecords to delete:")
    print(json.dumps(to_delete, indent=2, ensure_ascii=False))
    print("\nRecords to save/update:")
    print(json.dumps(desired, indent=2, ensure_ascii=False))

    if args.dry_run:
        print("\nDry run only. Re-run with --apply to update DNS.")
        return

    if to_delete:
        print("\nDeleting conflicting records...")
        delete_records(to_delete)
        time.sleep(1)

    print("Saving Vercel records...")
    put_records(desired)

    print("\nUpdated records:")
    updated = get_records()
    for r in updated:
        if norm_name(r) in {"@", "www"}:
            print(" -", json.dumps(r, ensure_ascii=False))
    print("\nDone. DNS propagation may take several minutes.")


if __name__ == "__main__":
    main()
