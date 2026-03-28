"""Run once to generate assets/icon.png"""
from PIL import Image, ImageDraw

img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.ellipse([4, 4, 60, 60], fill=(34, 197, 94, 255))   # green circle
draw.polygon([(20, 44), (32, 20), (44, 44)], fill=(255, 255, 255, 230))  # white triangle
img.save("assets/icon.png")
print("icon.png generated")
