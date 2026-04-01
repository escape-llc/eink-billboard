import logging
import os
from typing import Any, Mapping

from PIL import Image, ImageOps, ImageFilter
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult

def list_files_in_folder(folder_path):
	"""Return a list of image file paths in the given folder, excluding hidden files."""
	image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp')
	return [
		os.path.join(folder_path, fx)
		for fx in os.listdir(folder_path)
		if (
			os.path.isfile(os.path.join(folder_path, fx))
			and fx.lower().endswith(image_extensions)
			and not fx.startswith('.')
		)
	]

def grab_image(image_path, dimensions, pad_image, logger):
	"""Load an image from disk, auto-orient it, and resize to fit within the specified dimensions, preserving aspect ratio."""
	try:
		img = Image.open(image_path)
		img = ImageOps.exif_transpose(img)  # Correct orientation using EXIF
		img = ImageOps.contain(img, dimensions, Image.Resampling.LANCZOS)

		if pad_image:
			bkg = ImageOps.fit(img, dimensions)
			bkg = bkg.filter(ImageFilter.BoxBlur(8))
			img_size = img.size
			bkg.paste(img, ((dimensions[0] - img_size[0]) // 2, (dimensions[1] - img_size[1]) // 2))
			img = bkg
		return img
	except Exception as e:
		logger.error(f"Error loading image from {image_path}: {e}")
		return None

class ImageFolderAsync(DataSource, MediaListAsync, MediaRenderAsync):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)
	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> list:
		folder_path = params.get('folder')
		image_files = list_files_in_folder(folder_path)
		return image_files
	async def render_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any], state:Any) -> MediaRenderResult | None:
		if state is None:
			return None
		img = grab_image(state, dsec.dimensions, pad_image=True, logger=self.logger)
		return None if img is None else MediaRenderResult(image=img, title="Image Folder")
