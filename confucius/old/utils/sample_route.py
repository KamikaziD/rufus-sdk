import random
import string
import shutil
import os

from old.utils.minio_util import format_file_size, upload_image_minio, save_images, optimise_image


@router.post("/")
async def upload_image(
        player_or_club_id: str,
        image_type: enums.ImageUploadType,
        profile_type: enums.PlayerOrClubType,
        images: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
):
    urls = []
    print("IMAGES: ", images)
    for image in images:
        ext = image.filename.split(".")[1]
        accepted_file_types = ['jpg', 'png', 'JPEG', 'JPG', 'jpeg']
        if ext not in accepted_file_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type error, only '.jpg', .JPG, '.JPEG', 'jpeg', '.png' file types allowed")

        if image.size > 2097152:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File size limit < {format_file_size(2097152)}")

        # Generate a random string to add to the filename to avoid duplication
        letter = string.ascii_letters
        random_string = ''.join(random.choice(letter) for i in range(6))
        new = f"_{random_string}."
        filename = new.join(image.filename.rsplit(".", 1))
        path = f"images/{image.filename}"

        mimetype = image.content_type

        # Write the file to the images folder
        with open(path, "w+b") as buffer:
            shutil.copyfileobj(image.file, buffer)
        # Optimise image
        await optimise_image(path)

        url = await upload_image_minio(path, filename, player_or_club_id, image_type, mimetype)

        if image_type == enums.ImageUploadType.profile:
            if profile_type == enums.PlayerOrClubType.player:
                update_status = await update_player_profile_image(player_or_club_id, url, db)

                if update_status != status.HTTP_200_OK:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Something went wrong")

            if profile_type == enums.PlayerOrClubType.club_user:
                update_status = await update_user_profile_image(player_or_club_id, url, db)

                if update_status != status.HTTP_200_OK:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Something went wrong")

        if profile_type == enums.PlayerOrClubType.club:
            if image_type == enums.ImageUploadType.club_logo:
                update_status = await update_club_logo_image(player_or_club_id, url, db)

                if update_status != status.HTTP_200_OK:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Something went wrong")

            if image_type == enums.ImageUploadType.club_images:
                update_status = await update_club_images(player_or_club_id, url, db)

                if update_status != status.HTTP_200_OK:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Something went wrong")

        urls.append({
            'filename': filename,
            'url': url,
            'player_club_id': player_or_club_id,
            'image_type': image_type
        })

    res = await save_images(urls, db)
    for item in images:
        if os.path.exists(f"images/{item.filename}"):
            print("exists", f"images/{item.filename}")
            os.remove(f"images/{item.filename}")
        else:
            print("The file does not exist")

    return res
