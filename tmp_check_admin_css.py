import re
import requests

url = "https://stoicsocial-web-production.up.railway.app/admin/"
html = requests.get(url, timeout=20).text
links = sorted(set(re.findall(r"/static/admin/css/[^\"']+", html)))
print("CSS links found:")
for link in links:
    print(link)
print("count", len(links))

for link in links[:3]:
    full = "https://stoicsocial-web-production.up.railway.app" + link
    r = requests.get(full, timeout=20)
    print(link, r.status_code)
