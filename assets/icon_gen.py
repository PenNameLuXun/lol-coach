"""Run once to generate assets/icon.png"""
import pathlib
from PIL import Image, ImageDraw

img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.ellipse([4, 4, 60, 60], fill=(34, 197, 94, 255))   # green circle
draw.polygon([(20, 44), (32, 20), (44, 44)], fill=(255, 255, 255, 230))  # white triangle
out = pathlib.Path(__file__).parent / "icon.png"
img.save(out)
print("icon.png generated")
