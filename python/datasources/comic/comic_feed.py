from concurrent.futures import Future
from PIL import Image, ImageDraw, ImageFont
import requests

from ...model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from .comic_parser import get_items
from ..data_source import DataSource, DataSourceExecutionContext, MediaList, MediaRender

class ComicFeed(DataSource, MediaList, MediaRender):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
	def open(self, dsec: DataSourceExecutionContext, params: dict[str, any]) -> Future[list]:
		if self._es is None:
			raise RuntimeError("Executor not set for DataSource")
		comic = params.get("comic")
		def future_feed_download():
			return get_items(comic)
		future = self._es.submit(future_feed_download)
		return future
	def render(self, context: DataSourceExecutionContext, params:dict[str,any], state:any) -> Future[Image.Image | None]:
		if self._es is None:
			raise RuntimeError("Executor not set for DataSource")
		def future_feed_image():
			if state is None:
				return None
			img = self._generate_image(context, params, state)
			return img
		future = self._es.submit(future_feed_image)
		return future
	def _generate_image(self, context: DataSourceExecutionContext, params, item) -> Image.Image:
		scm = context.provider.required(SettingsConfigurationManager)
		stm = context.provider.required(StaticConfigurationManager)
		display_cob = scm.open("display")
		_, display_settings = display_cob.get()
		dimensions = context.dimensions
		is_caption = params.get("titleCaption") == "true"
		caption_font_size = params.get("fontSize", 16)
		if display_settings.get("orientation") == "vertical":
			dimensions = dimensions[::-1]
		width, height = dimensions
		caption_font = stm.get_font("Jost", font_size=int(caption_font_size)) if is_caption else None
		img = self._compose_image(item, caption_font, width, height)
		return img
	def _compose_image(self, item, caption_font, width, height):
		response = requests.get(item["image_url"], stream=True)
		response.raise_for_status()

		with Image.open(response.raw) as img:
			background = Image.new("RGB", (width, height), "white")
			draw = ImageDraw.Draw(background)
			top_padding, bottom_padding = 0, 0

			if caption_font is not None:
				if item["title"]:
					lines, wrapped_text = self._wrap_text(item["title"], caption_font, width)
					draw.multiline_text((width // 2, 0), wrapped_text, font=caption_font, fill="black", anchor="ma")
					top_padding = caption_font.getbbox(wrapped_text)[3] * lines + 1

				if item["caption"]:
					lines, wrapped_text = self._wrap_text(item["caption"], caption_font, width)
					draw.multiline_text((width // 2, height), wrapped_text, font=caption_font, fill="black", anchor="md")
					bottom_padding = caption_font.getbbox(wrapped_text)[3] * lines + 1

			scale = min(width / img.width, (height - top_padding - bottom_padding) / img.height)
			new_size = (int(img.width * scale), int(img.height * scale))
			img = img.resize(new_size, Image.LANCZOS)

			y_middle = (height - img.height) // 2
			y_top_bound = top_padding
			y_bottom_bound = height - img.height - bottom_padding

			xx = (width - img.width) // 2
			yy = yy = min(max(y_middle, y_top_bound), y_bottom_bound)

			background.paste(img, (xx, yy))
			return background
	def _wrap_text(self, text, font, width):
		lines = []
		words = text.split()[::-1]

		while words:
			line = words.pop()
			while words and font.getbbox(line + ' ' + words[-1])[2] < width:
				line += ' ' + words.pop()
			lines.append(line)

		return len(lines), '\n'.join(lines)