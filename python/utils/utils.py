import logging
import socket
import subprocess
from PIL import Image, ImageDraw

from ..model.configuration_manager import StaticConfigurationManager

logger = logging.getLogger(__name__)

FONTS = {
	"ds-gigi": "DS-DIGI.TTF",
	"napoli": "Napoli.ttf",
	"jost": "Jost.ttf",
	"jost-semibold": "Jost-SemiBold.ttf"
}

def get_wifi_name():
	try:
		output = subprocess.check_output(['iwgetid', '-r']).decode('utf-8').strip()
		return output
	except subprocess.CalledProcessError:
		return None

def generate_startup_image(stm:StaticConfigurationManager, dimensions=(800,480)):
	bg_color = (255,255,255)
	text_color = (0,0,0)
	width,height = dimensions

	hostname = socket.gethostname()

	image = Image.new("RGBA", dimensions, bg_color)
	image_draw = ImageDraw.Draw(image)

	title_font_size = width * 0.145
	image_draw.text((width/2, height/2), "inkypi", anchor="mm", fill=text_color, font=stm.get_font("Jost", title_font_size))

	text = f"To get started, visit http://{hostname}.local"
	text_font_size = width * 0.032
	image_draw.text((width/2, height*3/4), text, anchor="mm", fill=text_color, font=stm.get_font("Jost", text_font_size))

	return image
