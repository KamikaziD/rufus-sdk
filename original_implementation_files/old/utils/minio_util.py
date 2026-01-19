import os
import math
from dotenv import load_dotenv
from typing import List
import mimetypes
from minio import Minio

from PIL import Image


# from db.models import PlayerImages

# from credentials import credentials

# from enums.enums import ImageUploadType

load_dotenv()

SECRET_KEY = os.environ['SECRET_KEY']
ACCESS_KEY = os.environ['ACCESS_KEY']
BUCKET_NAME = os.environ['BUCKET_NAME']


def format_file_size(size, decimals=2):
    """Convert byte to relevant user readable size"""
    units = ['B', 'kB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB']
    largest_unit = 'YB'
    step = 1024
    for unit in units:
        if size < step:

            return ('%.' + str(decimals) + 'f %s') % (size, unit)
        size /= step
    return ('%.' + str(decimals) + 'f %s') % (size, largest_unit)


async def delete_image_s3(filename, user, image_type):
    client = Minio(
        'localhost:9000',
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY,
        secure=False,
    )
    bucket_name = BUCKET_NAME
    folder = user
    object_name = filename
    object_key = f"{folder}/{image_type}/{object_name}"
    print(object_key)
    try:
        client.remove_object(bucket_name=bucket_name, object_name=object_key)
        return {
            'object': object_key,
            'status': "Deleted"
        }
    except Exception as e:
        return e


async def upload_image_minio(filepath, filename, mimetype):
    if not filepath:
        return "error"

    client = Minio(
        'localhost:9000',
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY,
        secure=False,
    )

    bucket_name = BUCKET_NAME
    object_name = filename
    object_path = f"{object_name}"
    # mimetype = 'image/jpeg'
    print(mimetype)
    try:
        client.fput_object(bucket_name=bucket_name, file_path=filepath,
                           object_name=object_path, content_type=mimetype)
        # s3.upload_file(filepath, bucket_name, f"{player}/{image_type}/{object_name}", ExtraArgs={
        #     "ContentType": mimetype
        # })
        url = f"http://localhost:9000/{bucket_name}/{filename}"
        # url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{player}/{image_type}/{filename}"

        return url
    except Exception as e:
        print("ERROR: ", e)


async def save_images(urls: List, db):
    res = []
    for item in urls:
        new_file = PlayerImages(
            filename=item['filename'],
            url=item['url'],
            player_club_id=item['player_club_id'],
            image_type=item['image_type']
        )
        db.add(new_file)
        db.commit()
        db.refresh(new_file)
        db_res = {
            "id": new_file.id,
            "player_club_id": new_file.player_club_id,
            "filename": new_file.filename,
            "url": new_file.url,
            "image_type": new_file.image_type
        }
        res.append(db_res)
    return res


async def optimise_image(img):
    image = Image.open(img)
    original_size = os.path.getsize(img)
    width, height = image.size
    ratio = width / height
    new_height = float(1024 / ratio)
    new_width = 1024
    resized_image = image

    print("RATIO: ", ratio, new_width, new_height)
    if width > 1024:
        print("Resizing and Optimising - bigger than 1024")
        new_size = (int(new_width), int(new_height))
        resized_image = image.resize(new_size)
        resized_image.save(img, optimize=True, quality=80)
    elif 1024 > width > 640:
        print("Resizing and Optimising - between 800 and 640")
        new_width = float(width * 0.7)
        new_height = float(height * 0.7)
        new_size = (int(new_width), int(new_height))
        resized_image = image.resize(new_size)
        resized_image.save(img, optimize=True, quality=80)
    else:
        print("Optimising")
        resized_image.save(img, optimize=True, quality=80)

    compressed_size = os.path.getsize(img)
    percentage = compressed_size / original_size * 100
    print(
        f"New size: W: {math.ceil(new_width*100)/100} : H {math.ceil(new_height*100)/100}"
        f" - Size: {format_file_size(compressed_size)} vs "
        f"Original: W: {width} : H {height} - Size: {format_file_size(original_size)}")
    print(f"File is: {math.ceil(percentage*100)/100}% of the original")

    return resized_image
