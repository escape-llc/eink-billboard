from typing import IO, Any, Mapping
from PIL import Image, ImageDraw, ImageFont

from ...model.configuration_manager import SettingsConfigurationManager, StaticConfigurationManager
from ...task.async_http_worker_pool import client_var
from ...utils.image_utils import stream_to_buffer, to_rgb
from .comic_parser import get_items_async
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions

def _wrap_text(text, font, width):
	lines = []
	words = text.split()[::-1]
	while words:
		line = words.pop()
		while words and font.getbbox(line + ' ' + words[-1])[2] < width:
			line += ' ' + words.pop()
		lines.append(line)
	return len(lines), '\n'.join(lines)

def _compose_image(bytes:IO[bytes], item:dict, caption_font, width, height):
	with Image.open(bytes) as opened:
		# transparent comics go onto white paper, not black (and paste() below takes no mask)
		img = to_rgb(opened)
		background = Image.new("RGB", (width, height), "white")
		draw = ImageDraw.Draw(background)
		top_padding, bottom_padding = 0, 0

		if caption_font is not None:
			if item["title"]:
				lines, wrapped_text = _wrap_text(item["title"], caption_font, width)
				draw.multiline_text((width // 2, 0), wrapped_text, font=caption_font, fill="black", anchor="ma")
				top_padding = caption_font.getbbox(wrapped_text)[3] * lines + 1

			if item["caption"]:
				lines, wrapped_text = _wrap_text(item["caption"], caption_font, width)
				draw.multiline_text((width // 2, height), wrapped_text, font=caption_font, fill="black", anchor="md")
				bottom_padding = caption_font.getbbox(wrapped_text)[3] * lines + 1

		available = height - top_padding - bottom_padding
		if available < max(1, height // 4):
			# a long caption (SMBC hovertext) on a small/portrait display would leave no room for the comic: drop the caption, not the comic
			background = Image.new("RGB", (width, height), "white")
			top_padding = bottom_padding = 0
			available = height
		scale = min(width / img.width, available / img.height)
		new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
		img = img.resize(new_size, Image.Resampling.LANCZOS)

		y_middle = (height - img.height) // 2
		y_top_bound = top_padding
		y_bottom_bound = height - img.height - bottom_padding

		xx = (width - img.width) // 2
		yy = min(max(y_middle, y_top_bound), y_bottom_bound)

		background.paste(img, (xx, yy))
		return background


class ComicFeedAsync(DataSource, MediaListAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
	async def open_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any]) -> list:
		comic = params.get("comic")
		items = await get_items_async(comic)
		return items
	async def render_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any], state:Any) -> MediaRenderResult | None:
		if state is None:
			return None
		mrr = await self._generate_image(dsec, params, state)
		return mrr
	async def _generate_image(self, context: DataSourceExecutionContext, params, item) -> MediaRenderResult | None:
		scm = context.provider.required(SettingsConfigurationManager)
		stm = context.provider.required(StaticConfigurationManager)
		display_cob = scm.open("display")
		_, display_settings = display_cob.get()
		if display_settings is None:
			raise ValueError("display settings is None")
		# titleCaption is a boolean setting (older documents may hold the string "true")
		is_caption = params.get("titleCaption") in (True, "true")
		caption_font_size = params.get("fontSize", 16)
		width, height = target_dimensions(context, display_settings)
		caption_font = stm.get_font("Jost", font_size=int(caption_font_size)) if is_caption else None
		img = await self._download_and_compose_image(item, caption_font, width, height)
		return MediaRenderResult(image=img, title=item.get("title", "Comic"))
	async def _download_and_compose_image(self, item, caption_font, width, height):
		client = client_var.get()
		buffer = await stream_to_buffer(client, item["image_url"])
		return _compose_image(buffer, item, caption_font, width, height)
