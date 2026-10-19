"""The two prompts every model gets. Images are referred to by their position in the request."""
from __future__ import annotations

STYLE_RULES = (
    "the same brushy, grainy textures, warm saturated palette, soft shading, rounded shapes, "
    "big expressive eyes and line quality. Do not copy any characters, animals or objects from it."
)

# For a model that takes one image only: the style has to be described in words.
STYLE_WORDS = (
    "a modern children's picture book illustration: digital gouache with visible brushy, grainy "
    "textures, warm saturated colours (teal, orange, mustard), soft shading, rounded shapes, "
    "big expressive eyes with highlights, rosy cheeks."
)

LIKENESS = (
    "face shape, skin tone, hair colour, hairstyle and hairline, eye colour, eyebrows, ears, and any "
    "distinctive features such as freckles, dimples or gaps in the teeth, simplified the way the style "
    "simplifies faces"
)

NO_TEXT = "No text, letters, speech bubbles, captions or signatures anywhere in the picture."


def sheet(name: str, outfit: str, single_image: bool) -> str:
    if single_image:
        intro = (f"The image is a photo of a real child called {name}. Draw this child as a character in "
                 f"{STYLE_WORDS}")
    else:
        intro = (f"Image 1 is a photo of a real child called {name}. Image 2 is a page from a children's "
                 f"picture book and shows the art style only.\n"
                 f"Draw this child as a character in exactly the art style of image 2: {STYLE_RULES}")
    return (
        f"{intro}\n"
        f"Keep what makes the child recognisable: {LIKENESS}.\n"
        f"Make a character reference sheet on a plain cream background: the same child four times, side by "
        f"side: front view full body, three-quarter view full body, side view full body, and a close-up of the "
        f"face smiling. The same outfit in every view: {outfit}.\n"
        f"{NO_TEXT}"
    )


def page(name: str, outfit: str, scene: str, text_side: str, single_image: bool, with_photo: bool) -> str:
    if single_image:
        refs = (f"The image is a character sheet for {name}, the hero of a children's picture book. "
                f"Draw in the same style as the sheet: {STYLE_WORDS}")
    else:
        refs = (f"Image 1 is a character sheet for {name}, the hero of a children's picture book. "
                f"Image 2 shows the book's art style."
                + (" Image 3 is a photo of the real child, for likeness only." if with_photo else "")
                + f"\nDraw in exactly the art style of image 2: {STYLE_RULES}")
    return (
        f"{refs}\n"
        f"Draw one illustration for a two-page spread of the book.\n"
        f"{name} must look exactly like the character on the sheet: the same face, hair, skin tone and "
        f"proportions, wearing {outfit} unless the scene says otherwise.\n"
        f"Scene: {scene}\n"
        f"Composition: a wide landscape picture that fills the whole frame edge to edge. Keep the {text_side} "
        f"third of the picture calm (sky, wall, floor or soft background, no faces or important details), "
        f"because the story text will be printed there. Keep faces and hands away from the exact centre, where "
        f"the book folds, and away from the top and bottom edges.\n"
        f"{NO_TEXT}"
    )
