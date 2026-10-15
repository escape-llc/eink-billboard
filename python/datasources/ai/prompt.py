"""What a text part is asked to do with a prompt, and what an image part adds to every prompt: the same for every provider."""

def rewrite_request(prompt: str) -> tuple[str, str]:
	"""The `instructions` and the `input` that make a text model write an image prompt: a new one from nothing, or this one made vivid."""
	if not prompt.strip():
		return (
			"You are a creative assistant generating extremely random and unique image prompts. "
			"Avoid common themes. Focus on unexpected, unconventional, and bizarre combinations "
			"of art style, medium, subjects, time periods, and moods. No repetition. Prompts "
			"should be 20 words or less and specify random artist, movie, tv show or time period "
			"for the theme. Do not provide any headers or repeat the request, just provide the "
			"updated prompt in your response.",
			"Give me a completely random image prompt, something unexpected and creative! "
			"Let's see what your AI mind can cook up!",
		)
	return (
		"You are a creative assistant specializing in generating highly descriptive "
		"and unique prompts for creating images. When given a short or simple image "
		"description, your job is to rewrite it into a more detailed, imaginative, "
		"and descriptive version that captures the essence of the original while "
		"making it unique and vivid. Avoid adding irrelevant details but feel free "
		"to include creative and visual enhancements. Avoid common themes. Focus on "
		"unexpected, unconventional, and bizarre combinations of art style, medium, "
		"subjects, time periods, and moods. Do not provide any headers or repeat the "
		"request, just provide your updated prompt in the response. Prompts "
		"should be 20 words or less and specify random artist, movie, tv show or time "
		"period for the theme.",
		f"Original prompt: \"{prompt}\"\n"
		"Rewrite it to make it more detailed, imaginative, and unique while staying "
		"true to the original idea. Include vivid imagery and descriptive details. "
		"Avoid changing the subject of the prompt.",
	)

# added to every prompt: a panel shows the whole canvas, with few colors
CANVAS = (
	". The image should fully occupy the entire canvas without any frames, "
	"borders, or cropped areas. No blank spaces or artificial framing. "
	"Focus on simplicity, bold shapes, and strong contrast to enhance clarity "
	"and visual appeal. Avoid excessive detail or complex gradients, ensuring "
	"the design works well with flat, vibrant colors."
)
