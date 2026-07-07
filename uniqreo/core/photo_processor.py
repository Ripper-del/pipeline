import random
from PIL import Image, ImageOps, ImageEnhance

def process_photo(image, output_path):
    """
    accepts image as a parameter and outputs a clear core
    """

    with Image.open(image) as img:
        # 1. opening an image with defense from rotation so that the photo doesn't rotate if we delete EXIF
        img = ImageOps.exif_transpose(img)

        # transforming image into rgb
        img = img.convert('RGB')

        width, height = img.size

        # 2. random micro crops
        crop_top = random.randint(1, 4)
        crop_bottom = random.randint(1, 4)
        crop_left = random.randint(1, 4)
        crop_right = random.randint(1, 4)
        img = img.crop((crop_left, crop_top, width-crop_right, height-crop_bottom))

        # 3. mirroring the image with 50% chance
        if random.choice([True, False]):
            img = ImageOps.mirror(img)

        # 4. color cor
        enhancer_brightness = ImageEnhance.Brightness(img)
        img = enhancer_brightness.enhance(random.uniform(0.97, 1.03))

        enhancer_contrast = ImageEnhance.Contrast(img)
        img = enhancer_contrast.enhance(random.uniform(0.97, 1.03))

        # 5. noises
        noise_img = Image.effect_noise(img.size, random.uniform(10, 50)).convert('RGB')

        img = Image.blend(img, noise_img, alpha=random.uniform(0.01, 0.03))

        # 6. saving
        img.save(output_path, format='JPEG', quality=random.randint(90,100))