from concurrent.futures import Future
from PIL import Image
from openai import BadRequestError, OpenAI
import logging
from io import BytesIO
import base64
import requests
import openai

from ...model.configuration_manager import DatasourceConfigurationManager, SettingsConfigurationManager
from ..data_source import DataSource, DataSourceExecutionContext, MediaList, MediaRender

DEFAULT_IMAGE_MODEL = "dall-e-3"
DEFAULT_IMAGE_QUALITY = "standard"
IMAGE_MODELS = ["dall-e-3", "dall-e-2", "gpt-image-1"]
class OpenAI(DataSource, MediaList, MediaRender):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	def open(self, dsec: DataSourceExecutionContext, params: dict[str, any]) -> Future[list]:
		if self._es is None:
			raise RuntimeError("Executor not set for DataSource")
		def locate_image_url():
			dscm = dsec.provider.required(DatasourceConfigurationManager)
			scm = dsec.provider.required(SettingsConfigurationManager)
			ds_settings = dscm.load_settings()
			if not ds_settings:
				raise RuntimeError("Open AI Image datasource not configured.")
			api_key = ds_settings.get("apiKey", None)
			if not api_key:
					raise RuntimeError("OPEN AI API Key not configured.")
			text_prompt = params.get("prompt", "")
			image_model = params.get("imageModel", DEFAULT_IMAGE_MODEL)
			if image_model not in IMAGE_MODELS:
				raise RuntimeError(f"Invalid Image Model provided: {image_model}")
			image_quality = params.get('quality', "medium" if image_model == "gpt-image-1" else "standard")
			randomize_prompt = params.get('randomizePrompt') == True
			display_cob = scm.load_settings("display")
			_, display_settings = display_cob.get()
			orientation = display_settings.get("orientation", "landscape")
			return [{ "api_key": api_key, "text_prompt": text_prompt, "image_model": image_model, "image_quality": image_quality, "randomize_prompt": randomize_prompt, "orientation": orientation }]
		future = self._es.submit(locate_image_url)
		return future
	def render(self, context: DataSourceExecutionContext, params:dict[str,any], state:any) -> Future[Image.Image | None]:
		if self._es is None:
			raise RuntimeError("Executor not set for DataSource")
		def load_next():
			if state is None:
				return None
			image = self._dispatch_image(context, state.get('api_key'), state.get('image_model'), state.get('image_quality'), state.get('text_prompt'), state.get('randomize_prompt'), state.get('orientation'))
			return image
		future = self._es.submit(load_next)
		return future
	def _dispatch_image(self, context: DataSourceExecutionContext, api_key, image_model, image_quality, text_prompt, randomize_prompt, orientation) -> Image.Image | None:
		image = None
		try:
			ai_client = openai.OpenAI(api_key = api_key, timeout=60, max_retries=3)
			if randomize_prompt:
				text_prompt = OpenAI.fetch_image_prompt(self.logger, ai_client, text_prompt)

			image = OpenAI.fetch_image(
				self.logger,
				ai_client,
				text_prompt,
				model=image_model,
				quality=image_quality,
				orientation=orientation
			)
			return image
		except BadRequestError as bre:
			self.logger.error(f"Open AI Bad Request: {bre.body.get("message")}")
			raise RuntimeError(f"Open AI Bad Request: {bre.body.get("message")}")
		except Exception as e:
			self.logger.error(f"Failed to make Open AI request: {str(e)}")
			raise RuntimeError(f"Open AI request failure: {str(e)}")
	@staticmethod
	def fetch_image(logger, ai_client, prompt, model="dall-e-3", quality="standard", orientation="horizontal"):
		logger.info(f"fetch_image prompt: {prompt}, model: {model}, quality: {quality}")
		prompt += (
			". The image should fully occupy the entire canvas without any frames, "
			"borders, or cropped areas. No blank spaces or artificial framing."
		)
		prompt += (
			"Focus on simplicity, bold shapes, and strong contrast to enhance clarity "
			"and visual appeal. Avoid excessive detail or complex gradients, ensuring "
			"the design works well with flat, vibrant colors."
		)
		args = {
			"model": model,
			"prompt": prompt,
			"size": "1024x1024",
		}
		if model == "dall-e-3":
			args["size"] = "1792x1024" if orientation == "horizontal" else "1024x1792"
			args["quality"] = quality
		elif model == "gpt-image-1":
			args["size"] = "1536x1024" if orientation == "horizontal" else "1024x1536"
			args["quality"] = quality

		response = ai_client.images.generate(**args)
		if model in ["dall-e-3", "dall-e-2"]:
				image_url = response.data[0].url
				response = requests.get(image_url)
				img = Image.open(BytesIO(response.content))
		elif model == "gpt-image-1":
				image_base64 = response.data[0].b64_json
				image_bytes = base64.b64decode(image_base64)
				img = Image.open(BytesIO(image_bytes))
		return img

	@staticmethod
	def fetch_image_prompt(logger, ai_client, from_prompt=None):
		logger.info(f"fetch_image_prompt")

		system_content = (
			"You are a creative assistant generating extremely random and unique image prompts. "
			"Avoid common themes. Focus on unexpected, unconventional, and bizarre combinations "
			"of art style, medium, subjects, time periods, and moods. No repetition. Prompts "
			"should be 20 words or less and specify random artist, movie, tv show or time period "
			"for the theme. Do not provide any headers or repeat the request, just provide the "
			"updated prompt in your response."
		)
		user_content = (
			"Give me a completely random image prompt, something unexpected and creative! "
			"Let's see what your AI mind can cook up!"
		)
		if from_prompt and from_prompt.strip():
			system_content = (
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
				"period for the theme."
			)
			user_content = (
				f"Original prompt: \"{from_prompt}\"\n"
				"Rewrite it to make it more detailed, imaginative, and unique while staying "
				"true to the original idea. Include vivid imagery and descriptive details. "
				"Avoid changing the subject of the prompt."
			)

		# Make the API call
		response = ai_client.chat.completions.create(
			model="gpt-4o",
			messages=[
				{
					"role": "system",
					"content": system_content
				},
				{
					"role": "user",
					"content": user_content
				}
			],
			temperature=1
		)

		prompt = response.choices[0].message.content.strip()
		logger.info(f"fetch_image_prompt.Generated: {prompt}")
		return prompt
