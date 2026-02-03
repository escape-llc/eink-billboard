import json
import hashlib
import threading

HASH_KEY = "_rev"

def create_hash(data:dict):
	"""
	Computes a SHA256 hash of a JSON-serializable object and returns it.

	This function first removes any existing HASH_KEY key to ensure the hash is
	always based purely on the object's content.
	Args:
		data (dict): The dictionary to process.
	Returns:
		str: The computed SHA256 hash in hexadecimal format.
	"""
	for_hash = data.copy()

	# Remove the existing hash key if it is present.
	# The `pop` method with a default value of `None` prevents a KeyError.
	for_hash.pop(HASH_KEY, None)

	# Serialize the cleaned data into a canonical string.
	# `sort_keys=True` ensures consistent key order.
	# `separators=(',', ':')` removes whitespace for a compact string.
	canonical_string = json.dumps(
			for_hash,
			sort_keys=True,
			separators=(',', ':')
	)

	byte_string = canonical_string.encode('utf-8')
	object_hash = hashlib.sha256(byte_string).hexdigest()

	return object_hash

class HashEntry:
	def __init__(self, id:str, path:str, hash:str):
		self.id = id
		self.path = path
		self.hash = hash

class HashManager:
	def __init__(self, root_path: str = "."):
		self.root_path = root_path
		self.lock = threading.Lock()
		self.hashdict = {}
	def evict(self, path:str):
		with self.lock:
			entries_to_remove = [id for id, entry in self.hashdict.items() if entry.path == path]
			for id in entries_to_remove:
				del self.hashdict[id]
	def hash_document(self, id:str, path:str, document:dict):
		"""
		Hashes the provided document and stores the hash associated with the given ID.
		If the document's hash matches the existing hash for the ID, no update is made.
		Args:
			id (str): The unique identifier for the document.
			document (dict): The document to hash.
		Returns:
			tuple: A tuple containing:
				- bool: True if the hash was updated, False if it remained the same.
				- str: The new(True) or existing(False) hash of the document.
		"""
		with self.lock:
			old_hash = self.hashdict.get(id, None)
			new_hash = create_hash(document)
			if old_hash is not None and old_hash == new_hash:
				return False, old_hash
			self.hashdict[id] = HashEntry(id, path, new_hash)
			return True, new_hash
	def commit_document(self, id:str, path:str, document:dict, commit: callable):
		"""
		Commits the provided document if its current hash matches the stored hash for the given ID.
		Args:
			id (str): The unique identifier for the document.
			path (str): The file path associated with the document (not used in this method).
			document (dict): The document to commit, which must include a HASH_KEY key.
			commit (callable): A function that takes the document as an argument and performs the commit action.
		Returns:
			tuple: A tuple containing:
				- bool: True if the commit was successful, False if there was a hash mismatch
				- str or None: The new hash if committed, None if not committed.
		Raises:
			ValueError: If the document does not contain the HASH_KEY key.
		"""
		with self.lock:
			doc_hash = document.get(HASH_KEY, None)
			if doc_hash is None:
				raise ValueError(f"Document missing {HASH_KEY} key")
			current_hash = self.hashdict.get(id, None)
			if current_hash is None:
				# document was evicted or never hashed, so we hash it now
				current_hash = HashEntry(id, path, create_hash(document))
				self.hashdict[id] = current_hash
				pass
			if current_hash.hash != doc_hash:
				return False,None
			new_hash = create_hash(document)
			commit(document)
			current_hash.hash = new_hash
			return True,new_hash
	def check_document_hash(self, id:str, path:str, document:dict):
		"""
		Checks if the provided document's hash matches the stored hash for the given ID.
		Args:
			id (str): The unique identifier for the document.
			path (str): The file path associated with the document (not used in this method).
			document (dict): The document to check, which must include a HASH_KEY key.
		Returns:
			tuple: A tuple containing:
				- bool: True if the hashes match, False otherwise.
				- str or None: The stored hash if it exists, None if no hash is stored.
		Raises:
			ValueError: If the document does not contain the HASH_KEY key.
		"""
		with self.lock:
			doc_hash = document.get(HASH_KEY, None)
			if doc_hash is None:
				raise ValueError(f"Document missing {HASH_KEY} key")
			old_hash = self.hashdict.get(id, None)
			if old_hash is None:
				return False, None
			if old_hash.hash == doc_hash:
				return True, old_hash.hash
			return False, old_hash.hash
