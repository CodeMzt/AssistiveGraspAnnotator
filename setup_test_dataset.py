"""Create a minimal test dataset for visual verification."""
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).parent / "test_dataset"
if root.exists():
    shutil.rmtree(str(root))

images_dir = root / "images" / "board_vga"
images_dir.mkdir(parents=True, exist_ok=True)
(root / "annotations").mkdir(exist_ok=True)
(root / "splits").mkdir(exist_ok=True)
(root / "generated").mkdir(exist_ok=True)

# Copy classes.yaml
shutil.copy(
    Path(__file__).parent / "examples" / "classes.yaml",
    root / "classes.yaml",
)

# Create 4 test images with simulated desktop objects
COLORS = {
    "phone": (63, 140, 255),
    "remote": (255, 159, 64),
    "box": (76, 209, 55),
    "cup": (255, 71, 87),
    "bottle": (165, 94, 234),
}

objects_layouts = [
    # Image 1: phone + cup
    [("phone", 100, 80, 300, 280), ("cup", 380, 150, 520, 340)],
    # Image 2: remote + box
    [("remote", 80, 120, 200, 200), ("box", 300, 100, 500, 350)],
    # Image 3: phone + bottle + cup
    [("phone", 50, 100, 200, 280), ("bottle", 250, 150, 350, 350), ("cup", 400, 80, 550, 300)],
    # Image 4: box + remote
    [("box", 120, 100, 350, 320), ("remote", 400, 180, 560, 300)],
]

for idx, objs in enumerate(objects_layouts, 1):
    img = Image.new("RGB", (640, 480), color=(60, 60, 60))
    draw = ImageDraw.Draw(img)

    # Desktop surface
    draw.rectangle([(0, 300), (640, 480)], fill=(120, 90, 60))

    for obj_type, x1, y1, x2, y2 in objs:
        color = COLORS.get(obj_type, (200, 200, 200))
        # Shadow (dark rectangle offset)
        draw.rectangle([(x1 + 6, y1 + 6), (x2 + 6, y2 + 6)], fill=(30, 30, 30))
        # Object
        draw.rectangle([(x1, y1), (x2, y2)], fill=color, outline=(255, 255, 255), width=3)
        # Label
        draw.text((x1 + 10, y1 + 10), obj_type, fill=(255, 255, 255))

    img.save(images_dir / f"{idx:06d}.jpg")

print(f"Test dataset created at: {root}")
print(f"Images: {list(images_dir.glob('*.jpg'))}")
