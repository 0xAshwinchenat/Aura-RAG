from typing import List, Dict, Any
from pydantic import BaseModel
from app.core.parser import ParsedDocument, ParsedSection

class DocumentChunk(BaseModel):
    text: str
    metadata: Dict[str, Any]

class RecursiveTextSplitter:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200, separators: List[str] = None):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", ". ", " ", ""]
        
        # Validation
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")

    def _split_text_recursive(self, text: str, separators: List[str]) -> List[str]:
        # If the text is already small enough, return it
        if len(text) <= self.chunk_size:
            return [text]

        # If we run out of separators, split by hard index
        if not separators:
            chunks = []
            start = 0
            step = self.chunk_size - self.chunk_overlap
            while start < len(text):
                chunks.append(text[start:start + self.chunk_size])
                start += step
            return chunks

        separator = separators[0]
        next_separators = separators[1:]

        # Split string by separator
        if separator == "":
            splits = list(text)
        else:
            splits = text.split(separator)

        chunks = []
        current_chunk = []
        current_len = 0

        for split in splits:
            split_len = len(split)
            # If adding this split exceeds chunk size
            if current_len + split_len + (len(separator) if current_chunk else 0) > self.chunk_size:
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                    
                    # Rebuild current_chunk to honor overlap
                    overlap_chunk = []
                    overlap_len = 0
                    for item in reversed(current_chunk):
                        item_cost = len(item) + (len(separator) if overlap_chunk else 0)
                        if overlap_len + item_cost <= self.chunk_overlap:
                            overlap_chunk.insert(0, item)
                            overlap_len += item_cost
                        else:
                            break
                    current_chunk = overlap_chunk
                    current_len = overlap_len

                # If the split itself is larger than chunk_size, split it recursively
                if split_len > self.chunk_size:
                    sub_chunks = self._split_text_recursive(split, next_separators)
                    if sub_chunks:
                        # Append all but the last sub-chunk
                        chunks.extend(sub_chunks[:-1])
                        # The last sub-chunk becomes the start of our next chunk
                        current_chunk = [sub_chunks[-1]]
                        current_len = len(sub_chunks[-1])
                else:
                    current_chunk.append(split)
                    current_len += split_len + (len(separator) if len(current_chunk) > 1 else 0)
            else:
                current_chunk.append(split)
                current_len += split_len + (len(separator) if len(current_chunk) > 1 else 0)

        if current_chunk:
            chunks.append(separator.join(current_chunk))

        return chunks

    def split_document(self, doc: ParsedDocument) -> List[DocumentChunk]:
        """
        Splits a ParsedDocument into chunks, preserving section/page metadata.
        """
        chunks = []
        if not doc.success:
            return chunks

        for sec_idx, section in enumerate(doc.sections):
            split_texts = self._split_text_recursive(section.text, self.separators)
            
            for chunk_idx, text in enumerate(split_texts):
                # Inherit all metadata from the parsed section
                metadata = section.metadata.copy()
                metadata["mime_type"] = doc.mime_type
                metadata["chunk_index"] = chunk_idx
                metadata["section_index"] = sec_idx
                
                # Strip excessive whitespace but preserve spacing
                clean_text = text.strip()
                if clean_text:
                    chunks.append(DocumentChunk(
                        text=clean_text,
                        metadata=metadata
                    ))
                    
        return chunks
