import asyncio
import random

async def process_video(input_path: str, output_path: str):

    # 1. generating random filters

    # speed
    speed_multiplier = random.uniform(0.98, 1.02)

    # proportional fps
    video_pts = 1.0 / speed_multiplier

    # tiny cropping
    crop_width = random.randint(2, 6)
    crop_height = random.randint(2, 6)

    # color cor
    brightness = random.uniform(-0.03, 0.03)
    contrast = random.uniform(0.97, 1.03)

    # 2. blending everything together
    # using dynamic noice
    vf_string = (
        f"crop=iw-{crop_width}:ih-{crop_height},"
        f"eq=brightness={brightness:.3f}:contrast={contrast:.3f},"
        f"noise=alls=1:allf=t+u,"
        f"setpts={video_pts:.3f}*PTS"
    )

    # 3. collecting audio filters

    af_string = f"atempo={speed_multiplier:.3f}"

    # 4. a command for invoking sys FFmpeg
    cmd = [
        "ffmpeg",
        "-y",                                       # rewrite file if it already exists
        "-i", input_path,                           # input file
        "-map_metadata", "-1",                      # deleting all EXIF and metadata
        "-vf", vf_string,                           # video-filters
        "-af", af_string,                           # audio-filters
        "-c:v", "libx264",                          # codec H.264 (gemini said that it's perfect for TikTok and Reels)
        "-preset", "fast",                          # balance between rendering and compression
        "-crf", str(random.randint(21, 26)),  # randomizing bitrate and quality
        "-c:a", "aac",                              # audio coding
        "-b:a", "128k",                             # audio bitrate
        output_path                                 # ready file
    ]

    # 5. loading async process
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    # waiting for rendering process to finish and reading logs
    stdout, stderr = await process.communicate()

    # if error
    if process.returncode != 0:
        raise Exception(f"FFmpeg library failed while working with file {input_path}:\n{stderr.decode()}")