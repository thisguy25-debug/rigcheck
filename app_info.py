"""RigCheck version and update checking.

To turn on update notifications, publish RigCheck on GitHub (see README.md) and put
your repository name below, for example UPDATE_REPO = "yourname/rigcheck".
Each new version is a GitHub Release whose tag matches APP_VERSION (like v1.5.0),
with RigCheck.exe attached.
"""

import json
import re
import ssl
import urllib.error
import urllib.request

APP_VERSION = "1.5.1"
UPDATE_REPO = "thisguy25-debug/rigcheck"


class UpdateCheckError(Exception):
    """Raised with a plain-language reason when the update check can't finish."""


def _vt(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")) or (0,)


def _contexts():
    """Windows' own certificate list first, then certifi's bundled one (if available)."""
    yield ssl.create_default_context()
    try:
        import certifi
        yield ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass


def _open(url, timeout, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"User-Agent": f"RigCheck/{APP_VERSION}", "Accept": accept})
    last = None
    for ctx in _contexts():
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
        except urllib.error.URLError as e:
            last = e
            if not isinstance(getattr(e, "reason", None), ssl.SSLError):
                raise  # only certificate problems are worth retrying with another list
    raise last


def _from_api(timeout):
    with _open(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest", timeout) as r:
        data = json.load(r)
    return data.get("tag_name", ""), data.get("html_url"), (data.get("body") or "").strip()[:600]


def _from_website(timeout):
    """GitHub's normal site redirects /releases/latest to the newest release's page.
    It isn't affected by the API's hourly limit."""
    with _open(f"https://github.com/{UPDATE_REPO}/releases/latest", timeout, accept="text/html") as r:
        final = r.geturl()
    m = re.search(r"/releases/tag/([^/?#]+)$", final)
    if not m:
        raise UpdateCheckError("There are no published releases on GitHub yet.")
    return urllib.request.unquote(m.group(1)), final, ""


def _reason(e):
    if isinstance(e, UpdateCheckError):
        return str(e)
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 404:
            return ("GitHub has no published release for this app. Make sure the newest release is "
                    "published (not a draft or pre-release) and the repository is public.")
        if e.code in (403, 429):
            return "GitHub's hourly check limit was reached. It resets within an hour."
        return f"GitHub answered with an error ({e.code}). Try again later."
    reason = getattr(e, "reason", e)
    if isinstance(reason, ssl.SSLError):
        return ("A security certificate check failed. Antivirus with 'HTTPS scanning' or a network "
                "filter is usually the cause.")
    text = str(reason).lower()
    if "getaddrinfo" in text or "name or service" in text or "nodename" in text:
        return "This PC couldn't find GitHub. Check the internet connection."
    if "timed out" in text or isinstance(reason, TimeoutError):
        return "GitHub didn't answer in time. Check the internet connection."
    if "refused" in text or "forbidden" in text or "10013" in text:
        return "The connection was blocked, usually by a firewall or antivirus. Allow RigCheck through it."
    return f"The connection failed ({reason})."


def check_for_update(timeout=8):
    """Returns {'version', 'url', 'notes'} if a newer release exists, or None if up to date.
    Raises UpdateCheckError with a readable reason if GitHub can't be reached."""
    if not UPDATE_REPO:
        return None
    errors = []
    for source in (_from_api, _from_website):
        try:
            tag, url, notes = source(timeout)
            break
        except Exception as e:  # try the other route, then report the clearest reason
            errors.append(e)
    else:
        # A 404 from the API plus "no releases" from the site means nothing is published;
        # otherwise the first network problem explains it best.
        def rank(e):  # most specific explanation first
            if isinstance(e, UpdateCheckError):
                return 0
            if isinstance(e, urllib.error.HTTPError):
                return 1 if e.code == 404 else 3
            return 2
        raise UpdateCheckError(_reason(min(errors, key=rank)))
    if _vt(tag) > _vt(APP_VERSION):
        return {"version": tag.lstrip("vV"), "url": url, "notes": notes}
    return None


def latest_release_tag(timeout=8):
    """For diagnostics: the newest published tag, or raises UpdateCheckError."""
    for source in (_from_api, _from_website):
        try:
            return source(timeout)[0]
        except Exception as e:
            last = e
    raise UpdateCheckError(_reason(last))
