#!/usr/bin/env python3
"""Render a terminal demo GIF for zmail using Pillow. Content is fictional."""
import sys
from PIL import Image, ImageDraw, ImageFont

REG_PATH = "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf"
BOLD_PATH = "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono-Bold.ttf"
SIZE = 24
REG = ImageFont.truetype(REG_PATH, SIZE)
BOLD = ImageFont.truetype(BOLD_PATH, SIZE)

# palette (GitHub dark-ish)
BG, BAR = "#0d1117", "#161b22"
FG = "#e6edf3"; DIM = "#6e7681"; GRAY = "#8b949e"
GREEN = "#7ee787"; YELLOW = "#f2cc60"; BLUE = "#58a6ff"; LBLUE = "#79c0ff"
CURSOR = "#e6edf3"

PAD_X, TITLE_H, TOP_PAD, LINE_H = 28, 46, 16, 34
PROMPT = ("$ ", GREEN, True)

# ---- content (fictional) --------------------------------------------------
CMD1 = "zmail check --unread"
OUT1 = [
    [("• ", YELLOW, False), ("[4821] ", BLUE, False), ("09:14  ", GRAY, False),
     ("program-chairs@confhub.org", LBLUE, False),
     ("   Reviews for submission #217 are ready", FG, False)],
    [("• ", YELLOW, False), ("[4820] ", BLUE, False), ("08:02  ", GRAY, False),
     ("alice@example.org", LBLUE, False),
     ("           Re: draft of section 4", FG, False)],
]
CMD2 = "zmail reply 4820 --quote --attach figure.png --attach results.csv"
OUT2 = [
    [("Reply draft saved to ", FG, False), ("'Drafts'", GREEN, True),
     (". Review & send from webmail.", FG, False)],
    [("  To: ", GRAY, False), ("alice@example.org", FG, False)],
    [("  Subject: ", GRAY, False), ("Re: draft of section 4", FG, False)],
]
COMMENT = [("# staged as a draft — you review & send.  ", DIM, False),
           ("github.com/natema/zimbra-skill", BLUE, False)]

def line_width(spans):
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    x = 0
    for text, _, bold in spans:
        x += tmp.textlength(text, font=(BOLD if bold else REG))
    return x

def cmd_line(cmd_text):
    return [PROMPT, (cmd_text, FG, True)]

# figure out canvas size from the widest possible line
ALL = [cmd_line(CMD1), *OUT1, cmd_line(CMD2), *OUT2, COMMENT]
WIDTH = int(max(line_width(l) for l in ALL)) + PAD_X * 2 + 16
N_LINES = 10  # cmd1, o,o, blank, cmd2, o,o,o, blank, comment
HEIGHT = TITLE_H + TOP_PAD + N_LINES * LINE_H + 16

def render(lines, cursor=False):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, WIDTH, TITLE_H], fill=BAR)
    for i, c in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        d.ellipse([PAD_X + i * 26, TITLE_H // 2 - 7, PAD_X + i * 26 + 14, TITLE_H // 2 + 7], fill=c)
    d.text((WIDTH // 2, TITLE_H // 2), "zmail — Zimbra mail for AI agents",
           font=REG, fill=GRAY, anchor="mm")
    y = TITLE_H + TOP_PAD
    end_x = PAD_X
    for spans in lines:
        x = PAD_X
        for text, color, bold in spans:
            d.text((x, y), text, font=(BOLD if bold else REG), fill=color)
            x += d.textlength(text, font=(BOLD if bold else REG))
        end_x = x
        y += LINE_H
    if cursor:
        cy = y - LINE_H
        d.rectangle([end_x + 2, cy + 3, end_x + 14, cy + SIZE + 2], fill=CURSOR)
    return img

BLANK = [("", FG, False)]

def build_animation():
    frames, durs, L = [], [], []
    def frame(active=None, cursor=False, dur=60):
        lines = list(L) + ([cmd_line(active)] if active is not None else [])
        frames.append(render(lines, cursor=cursor)); durs.append(dur)
    frame(active="", cursor=True, dur=550)
    for i in range(1, len(CMD1) + 1):
        frame(active=CMD1[:i], cursor=True, dur=45)
    frame(active=CMD1, cursor=True, dur=280)
    L.append(cmd_line(CMD1)); frame(dur=180)
    L.append(OUT1[0]); frame(dur=230)
    L.append(OUT1[1]); frame(dur=680)
    L.append(BLANK); frame(dur=120)
    frame(active="", cursor=True, dur=260)
    for i in range(1, len(CMD2) + 1):
        frame(active=CMD2[:i], cursor=True, dur=38)
    frame(active=CMD2, cursor=True, dur=300)
    L.append(cmd_line(CMD2)); frame(dur=170)
    L.append(OUT2[0]); frame(dur=240)
    L.append(OUT2[1]); frame(dur=210)
    L.append(OUT2[2]); frame(dur=560)
    L.append(BLANK); frame(dur=110)
    L.append(COMMENT); frame(dur=2600)
    return frames, durs

if __name__ == "__main__":
    if "--preview" in sys.argv:
        screen = [cmd_line(CMD1), *OUT1, BLANK, cmd_line(CMD2), *OUT2, BLANK, COMMENT]
        render(screen).save(sys.argv[sys.argv.index("--preview") + 1])
        print(f"preview saved {WIDTH}x{HEIGHT}")
    else:
        out = sys.argv[sys.argv.index("--gif") + 1] if "--gif" in sys.argv else "demo.gif"
        frames, durs = build_animation()
        pal = frames[-1].convert("P", palette=Image.ADAPTIVE, colors=64)
        pframes = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
        pframes[0].save(out, save_all=True, append_images=pframes[1:],
                        duration=durs, loop=0, optimize=True, disposal=2, format="GIF")
        print(f"gif saved {out}  {WIDTH}x{HEIGHT}  {len(frames)} frames")
