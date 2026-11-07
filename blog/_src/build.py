"""
Builds the blog from the Markdown files next to this script.

    pip install markdown
    python3 blog/_src/build.py

Writes blog/<slug>/index.html for each post and blog/index.html for the list.
A post is a .md file with a small header (title, date, summary) between --- lines.
"""

import datetime
import html
import os
import re

import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
BLOG = os.path.dirname(HERE)

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{summary}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{summary}">
<meta property="og:type" content="{og_type}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..800&family=Literata:ital,opsz,wght@0,7..72,400..700;1,7..72,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{root}assets/site.css">
<link rel="stylesheet" href="{root}assets/blog.css">
<script src="{root}assets/theme.js"></script>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<div class="bar">
  <div class="wrap">
    <a class="home" href="{root}">Aman Raj Verma</a>
    <nav aria-label="Main">
      <a href="{root}#projects">Projects</a>
      <a href="{root}blog/"{blog_current}>Writing</a>
      <a href="{root}resume.pdf">Resume</a>
      <button class="theme-toggle" type="button">Dark mode</button>
    </nav>
  </div>
</div>
"""

FOOT = """
<footer>
  <div class="wrap">
    <span><a href="{root}">Aman Raj Verma</a></span>
    <span><a href="mailto:amanrajverma003@gmail.com">amanrajverma003@gmail.com</a>&nbsp;&nbsp; <a href="https://github.com/ARV0007">GitHub</a></span>
  </div>
</footer>
</body>
</html>
"""


def parse(path):
    text = open(path, encoding="utf-8").read()
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    meta = dict(line.split(": ", 1) for line in m.group(1).splitlines())
    meta["slug"] = os.path.splitext(os.path.basename(path))[0]
    meta["body"] = m.group(2)
    return meta


def nice_date(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


def minutes(body):
    return max(1, round(len(re.findall(r"\w+", body)) / 220))


def build():
    posts = sorted((parse(os.path.join(HERE, f)) for f in os.listdir(HERE) if f.endswith(".md")),
                   key=lambda p: (p["date"], p["title"]), reverse=True)
    for p in posts:
        body = markdown.markdown(p["body"], extensions=["fenced_code", "tables"])
        out_dir = os.path.join(BLOG, p["slug"])
        os.makedirs(out_dir, exist_ok=True)
        page = HEAD.format(title=html.escape(p["title"]), summary=html.escape(p["summary"]), og_type="article",
                           root="../../", blog_current="")
        page += f"""
<main id="main" class="wrap">
  <article class="post">
    <header>
      <p class="meta"><a href="../">Writing</a>, {nice_date(p['date'])}, {minutes(p['body'])} min read</p>
      <h1>{html.escape(p['title'])}</h1>
      <p class="standfirst">{html.escape(p['summary'])}</p>
    </header>
    <div class="prose">
{body}
    </div>
  </article>
</main>
"""
        page += FOOT.format(root="../../")
        open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8").write(page)

    items = "\n".join(
        f"""    <li>
      <a href="{p['slug']}/"><h2>{html.escape(p['title'])}</h2></a>
      <p>{html.escape(p['summary'])}</p>
      <p class="meta">{nice_date(p['date'])}, {minutes(p['body'])} min read</p>
    </li>""" for p in posts)
    index = HEAD.format(title="Writing", summary="Notes on bugs I fixed and systems I built: what broke, why, and how I proved the fix.",
                        og_type="website", root="../", blog_current=' aria-current="page"')
    index += f"""
<main id="main" class="wrap">
  <div class="list-head">
    <h1>Writing</h1>
    <p class="lede">Notes on bugs I fixed and systems I built: what broke, why, and how I proved the fix.</p>
  </div>
  <ul class="posts">
{items}
  </ul>
</main>
"""
    index += FOOT.format(root="../")
    open(os.path.join(BLOG, "index.html"), "w", encoding="utf-8").write(index)
    print(f"built {len(posts)} posts")


if __name__ == "__main__":
    build()
