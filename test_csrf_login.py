#!/usr/bin/env python
"""Test CSRF login flow against live Railway app"""
import requests
from urllib.parse import urlparse, parse_qs
import re

url_base = "https://stoicsocial-web-production.up.railway.app"
login_url = f"{url_base}/accounts/login/?next=/ops/inventory/orders/"

print("=== CSRF LOGIN TEST ===\n")

# Step 1: GET login page and extract CSRF token
print(f"[1] GET {login_url}")
session = requests.Session()
try:
    r_get = session.get(login_url, timeout=10, verify=False)
    print(f"    Status: {r_get.status_code}")
    
    # Extract CSRF token
    match = re.search(r'csrfmiddlewaretoken["\s]*value="([^"]+)"', r_get.text)
    if not match:
        print("    ERROR: CSRF token not found in HTML")
        print(f"    Response headers: {dict(r_get.headers)}")
        print(f"    Response (first 500 chars): {r_get.text[:500]}")
    else:
        csrf_token = match.group(1)
        print(f"    CSRF token: {csrf_token[:20]}...")
        
        # Step 2: POST login
        print(f"\n[2] POST {url_base}/accounts/login/")
        data = {
            'username': 'ARC',
            'password': 'ARC@BoldERP2026!',
            'csrfmiddlewaretoken': csrf_token,
            'next': '/ops/inventory/orders/'
        }
        headers = {
            'Referer': login_url
        }
        
        try:
            r_post = session.post(
                f"{url_base}/accounts/login/",
                data=data,
                headers=headers,
                timeout=10,
                verify=False,
                allow_redirects=False
            )
            print(f"    Status: {r_post.status_code}")
            print(f"    Content-Type: {r_post.headers.get('Content-Type')}")
            print(f"    Location: {r_post.headers.get('Location', 'N/A')}")
            
            if r_post.status_code == 403:
                print("\n    ❌ CSRF FAILED (403)")
                # Extract error reason
                if 'CSRF' in r_post.text:
                    if 'Origin checking failed' in r_post.text:
                        print("    Reason: Origin checking failed")
                    elif 'Referer checking failed' in r_post.text:
                        print("    Reason: Referer checking failed")
                    elif 'CSRF cookie not set' in r_post.text:
                        print("    Reason: CSRF cookie not set")
                    elif 'CSRF token missing' in r_post.text:
                        print("    Reason: CSRF token missing")
                    elif 'CSRF token from POST incorrect' in r_post.text:
                        print("    Reason: CSRF token incorrect")
                print(f"\n    Response (first 1000 chars):\n{r_post.text[:1000]}")
            elif r_post.status_code == 302:
                print("\n    ✅ LOGIN SUCCESSFUL (302 redirect)")
                print(f"    Redirecting to: {r_post.headers.get('Location')}")
            else:
                print(f"\n    Unexpected status: {r_post.status_code}")
                print(f"    Response: {r_post.text[:500]}")
        except Exception as e:
            print(f"    ERROR: {e}")
except Exception as e:
    print(f"    ERROR: {e}")

print("\n=== COOKIES ===")
for name, value in session.cookies.items():
    print(f"{name}: {value[:30]}..." if len(value) > 30 else f"{name}: {value}")
