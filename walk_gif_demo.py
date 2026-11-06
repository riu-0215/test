import pygame
from pathlib import Path
from PIL import Image, ImageSequence

WIDTH, HEIGHT = 800, 600


def load_gif_frames(path, size):
    frames = []
    try:
        with Image.open(path) as img:
            for frame in ImageSequence.Iterator(img):
                rgba = frame.convert('RGBA')
                rgba = rgba.resize(size, Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS)
                surface = pygame.image.frombuffer(rgba.tobytes(), rgba.size, 'RGBA')
                frames.append(surface)
    except Exception as exc:
        print(f'GIF load failed: {exc}')
    return frames


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption('GIF Walk Animation')
    clock = pygame.time.Clock()

    gif_path = Path(__file__).resolve().parent / 'm (2)-animated.gif'
    frames = load_gif_frames(gif_path, (120, 120))
    if not frames:
        frames = [pygame.Surface((120, 120), pygame.SRCALPHA)]
        pygame.draw.rect(frames[0], (255, 0, 0), (10, 10, 100, 100))

    player_x = WIDTH // 2
    player_y = HEIGHT // 2
    speed = 4
    frame_index = 0
    frame_timer = 0
    moving = False

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        keys = pygame.key.get_pressed()
        dx = 0
        dy = 0
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            dy -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            dy += 1
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            dx -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            dx += 1

        moving = dx != 0 or dy != 0
        if moving:
            length = (dx * dx + dy * dy) ** 0.5
            if length:
                dx /= length
                dy /= length
            player_x += dx * speed
            player_y += dy * speed

        screen.fill((220, 220, 220))

        if moving:
            frame_timer += 1
            if frame_timer >= 5:
                frame_timer = 0
                frame_index = (frame_index + 1) % len(frames)
            current_frame = frames[frame_index]
            if dx < 0:
                current_frame = pygame.transform.flip(current_frame, True, False)
        else:
            frame_timer = 0
            frame_index = 0
            current_frame = frames[0]

        screen.blit(current_frame, (player_x - current_frame.get_width() // 2, player_y - current_frame.get_height() // 2))

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


if __name__ == '__main__':
    main()
