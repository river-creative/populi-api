"""File download, and profile pictures.

A person's photo is reached by the **top-level scalar** ``image_file_id`` on the
person — present regardless of ``expand`` — and then through one of the two
routes here.
"""

import logging

logger = logging.getLogger(__name__)


class Files:
    """Fetch files by id, and replace a person's profile picture."""

    def __init__(self, client):
        self._client = client

    def download_link(self, file_id):
        """A presigned, auth-free, time-limited URL for the file.

        Preferred over :meth:`download` when the bytes are going to a browser or
        another service: the link needs no API key, so nothing has to proxy the
        content or hold a credential to fetch it.
        """
        body = self._client.get('files/%s/download_link' % file_id)
        return body.get('download_link') or None

    def download(self, file_id):
        """The raw bytes of a file.

        Returns ``(content, content_type)``. Goes through the transport's
        session so pacing and retries still apply, but deliberately does not
        attempt to decode the body — this is the one route that is not JSON.
        """
        url = self._client.base_url + 'files/%s/download' % file_id
        self._client.pace()
        response = self._client.session.get(url, timeout=self._client.timeout)

        error = self._client.error_for(response, 'files/%s/download' % file_id)
        if error is not None:
            raise error

        return response.content, response.headers.get('Content-Type')

    def update_profile_picture(self, person_id, content, filename='photo.jpg'):
        """Replace a person's profile picture.

        **Send no Content-Type header** — the multipart boundary has to be
        written by the HTTP library, and Populi's own curl example wrongly adds
        ``application/json``, which breaks the upload. The form part is named
        literally ``file``.

        Returns the person with ``profile_picture_file`` expanded. **Verify on
        ``profile_picture_file.size``**, not on ``image_file_id`` changing:
        Populi replaces the picture in place, so that id never moves after the
        person's first photo and the obvious check reports every successful
        upload as a failure.
        """
        path = 'people/%s/update_profile_picture' % person_id
        url = self._client.base_url + path

        self._client.pace()
        response = self._client.session.post(
            url,
            files={'file': (filename, content)},
            timeout=self._client.timeout,
        )

        error = self._client.error_for(response, path)
        if error is not None:
            raise error

        return response.json() if response.content else {}
