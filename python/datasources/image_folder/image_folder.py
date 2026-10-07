import logging
import os
from typing import Any, Mapping

from PIL import Image, ImageOps, ImageFilter
from ...utils.image_utils import to_rgb
from ..data_source import DataSource, DataSourceExecutionContext, MediaListAsync, MediaRenderAsync, MediaRenderResult, target_dimensions

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
		with Image.open(image_path) as opened:
			img = ImageOps.exif_transpose(opened)  # Correct orientation using EXIF
			# palette ('P'), bilevel ('1') and alpha images cannot be blurred/pasted as they are; transparency goes onto white
			img = to_rgb(img)
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
		if not folder_path:
			raise ValueError("The 'folder' setting is required for the image folder datasource.")
		if not os.path.isdir(folder_path):
			raise ValueError("The 'folder' setting is not a folder that exists.")
		image_files = list_files_in_folder(folder_path)
		if not image_files:
			self.logger.warning(f"'{self.name}' no images found in the folder.")
		return image_files
	async def render_async(self, dsec: DataSourceExecutionContext, params:Mapping[str,Any], state:Any) -> MediaRenderResult | None:
		if state is None:
			return None
		img = grab_image(state, target_dimensions(dsec), pad_image=True, logger=self.logger)
		return None if img is None else MediaRenderResult(image=img, title="Image Folder")
