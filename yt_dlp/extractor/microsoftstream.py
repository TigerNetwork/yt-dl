from base64 import b64decode

from .common import InfoExtractor
from ..utils import (
    merge_dicts,
    parse_iso8601,
    parse_duration,
    parse_resolution,
    try_get,
    url_basename,
)


class MicrosoftStreamIE(InfoExtractor):
    IE_NAME = 'microsoftstream'
    IE_DESC = 'Microsoft Stream'
    _VALID_URL = r'https?://(?:web|www|msit)\.microsoftstream\.com/video/(?P<id>[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12})'

    _TESTS = [{
        'url': 'https://web.microsoftstream.com/video/6e51d928-4f46-4f1c-b141-369925e37b62?list=user&userId=f5491e02-e8fe-4e34-b67c-ec2e79a6ecc0',
        'only_matching': True,
    }, {
        'url': 'https://msit.microsoftstream.com/video/b60f5987-aabd-4e1c-a42f-c559d138f2ca',
        'only_matching': True,
    }]

    def _get_all_subtitles(self, api_url, video_id, headers):
        subtitles = {}
        automatic_captions = {}
        text_tracks = self._download_json(
            f'{api_url}/videos/{video_id}/texttracks', video_id,
            note='Downloading subtitles JSON', fatal=False, headers=headers,
            query={'api-version': '1.4-private'}).get('value') or []
        for track in text_tracks:
            if not track.get('language') or not track.get('url'):
                continue
            sub_dict = automatic_captions if track.get('autoGenerated') else subtitles
            sub_dict.setdefault(track['language'], []).append({
                'ext': 'vtt',
                'url': track.get('url')
            })
        return {
            'subtitles': subtitles,
            'automatic_captions': automatic_captions
        }

    def extract_all_subtitles(self, *args, **kwargs):
        if (self.get_param('writesubtitles', False)
                or self.get_param('writeautomaticsub', False)
                or self.get_param('listsubtitles')):
            return self._get_all_subtitles(*args, **kwargs)
        return {}

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)
        if '<title>Microsoft Stream</title>' not in webpage:
            self.raise_login_required(method='cookies')

        access_token = self._html_search_regex(r'"AccessToken":"(.+?)"', webpage, 'access token')
        api_url = self._html_search_regex(r'"ApiGatewayUri":"(.+?)"', webpage, 'api url')

        headers = {'Authorization': f'Bearer {access_token}'}

        video_data = self._download_json(
            f'{api_url}/videos/{video_id}', video_id,
            headers=headers, query={
                '$expand': 'creator,tokens,status,liveEvent,extensions',
                'api-version': '1.4-private'
            })
        video_id = video_data.get('id') or video_id
        language = video_data.get('language')

        thumbnails = []
        for thumbnail_id in ('extraSmall', 'small', 'medium', 'large'):
            thumbnail_url = try_get(video_data, lambda x: x['posterImage'][thumbnail_id]['url'], str)
            if not thumbnail_url:
                continue
            thumb = {
                'id': thumbnail_id,
                'url': thumbnail_url,
            }
            thumb_name = url_basename(thumbnail_url)
            thumb_name = str(b64decode(thumb_name + '=' * (-len(thumb_name) % 4)))
            thumb.update(parse_resolution(thumb_name))
            thumbnails.append(thumb)

        formats = []
        for playlist in video_data['playbackUrls']:
            if playlist['mimeType'] == 'application/vnd.apple.mpegurl':
                formats.extend(self._extract_m3u8_formats(
                    playlist['playbackUrl'], video_id,
                    ext='mp4', entry_protocol='m3u8_native', m3u8_id='hls',
                    fatal=False, headers=headers))
            elif playlist['mimeType'] == 'application/dash+xml':
                formats.extend(self._extract_mpd_formats(
                    playlist['playbackUrl'], video_id, mpd_id='dash',
                    fatal=False, headers=headers))
            elif playlist['mimeType'] == 'application/vnd.ms-sstr+xml':
                formats.extend(self._extract_ism_formats(
                    playlist['playbackUrl'], video_id, ism_id='mss',
                    fatal=False, headers=headers))
        formats = [merge_dicts(f, {'language': language}) for f in formats]
        self._sort_formats(formats)

        return {
            'id': video_id,
            'title': video_data['name'],
            'description': video_data.get('description'),
            'uploader': try_get(video_data, lambda x: x['creator']['name'], str),
            'uploader_id': try_get(video_data, (lambda x: x['creator']['mail'],
                                                lambda x: x['creator']['id']), str),
            'thumbnails': thumbnails,
            **self.extract_all_subtitles(api_url, video_id, headers),
            'timestamp': parse_iso8601(video_data.get('created')),
            'duration': parse_duration(try_get(video_data, lambda x: x['media']['duration'])),
            'webpage_url': f'https://web.microsoftstream.com/video/{video_id}',
            'view_count': try_get(video_data, lambda x: x['metrics']['views'], int),
            'like_count': try_get(video_data, lambda x: x['metrics']['likes'], int),
            'comment_count': try_get(video_data, lambda x: x['metrics']['comments'], int),
            'formats': formats,
        }
