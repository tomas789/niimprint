from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

# Create a new image with a white background
img = Image.new('RGB', (240, 120), color='white')

# Create a drawing object
draw = ImageDraw.Draw(img)

# Get today's date and format it in Czech style
today = datetime.now().strftime("%-d. %-m. %Y")

# Function to get font size that fits the image
def get_fitting_font_size(draw, text, max_width, max_height):
    font_size = 1
    font = ImageFont.load_default().font_variant(size=font_size)
    while font.getbbox(text)[2] < max_width and font.getbbox(text)[3] < max_height:
        font_size += 1
        font = ImageFont.load_default().font_variant(size=font_size)
    return font_size - 1

# Get the largest font size that fits
font_size = get_fitting_font_size(draw, today, 220, 100)

# Use the fitting font size
font = ImageFont.load_default().font_variant(size=font_size)

# Get the size of the text
text_bbox = draw.textbbox((0, 0), today, font=font)
text_width = text_bbox[2] - text_bbox[0]
text_height = text_bbox[3] - text_bbox[1]

# Calculate position to center the text
position = ((240-text_width)/2, (120-text_height)/2)

# Draw the text on the image
draw.text(position, today, fill='black', font=font)

# Save the image
img.save('date_image.png')

print(f"Image generated successfully with font size {font_size}.")
print("Image saved to date_image.png")
