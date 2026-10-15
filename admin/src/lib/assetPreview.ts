export interface AssetPreviewSource {
  preview_url?: string | null;
  thumbnail_url?: string | null;
}

export interface AssetPreview {
  href: string | null;
  thumbnail: string | null;
  kind: "image" | "video" | "embed" | "link";
  src: string | null;
  provider: string;
}

/** Register values can be empty, free text, or links. Only web URLs belong in the UI. */
export function webUrl(value: string | null | undefined): URL | null {
  if (!value?.trim()) return null;
  try {
    const url = new URL(value.trim());
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password
      ? url
      : null;
  } catch {
    return null;
  }
}

export function getAssetPreview(source: AssetPreviewSource): AssetPreview {
  const url = webUrl(source.preview_url);
  const thumbnail = webUrl(source.thumbnail_url)?.href ?? null;
  const preview: AssetPreview = {
    href: url?.href ?? thumbnail,
    thumbnail,
    kind: thumbnail ? "image" : "link",
    src: thumbnail,
    provider: "Asset",
  };
  if (!url) return preview;

  const host = url.hostname.toLowerCase().replace(/^www\./, "");
  if (host === "drive.google.com") {
    const pathId = url.pathname.match(/^\/file\/d\/([\w-]+)(?:\/|$)/)?.[1];
    const queryId = ["/open", "/uc"].includes(url.pathname) ? url.searchParams.get("id") : null;
    const id = pathId ?? queryId;
    if (id && /^[\w-]+$/.test(id)) {
      const embed = new URL(`https://drive.google.com/file/d/${id}/preview`);
      const thumb = new URL("https://drive.google.com/thumbnail");
      thumb.searchParams.set("id", id);
      thumb.searchParams.set("sz", "w200");
      const resourceKey = url.searchParams.get("resourcekey");
      if (resourceKey) {
        embed.searchParams.set("resourcekey", resourceKey);
        thumb.searchParams.set("resourcekey", resourceKey);
      }
      return { ...preview, kind: "embed", src: embed.href, thumbnail: thumbnail ?? thumb.href, provider: "Google Drive" };
    }
    return { ...preview, provider: "Google Drive" };
  }

  if (host === "instagram.com") {
    const post = url.pathname.match(/^\/(p|reel|reels|tv)\/([\w-]+)(?:\/|$)/);
    if (post) {
      const type = post[1] === "reels" ? "reel" : post[1];
      return { ...preview, kind: "embed", src: `https://www.instagram.com/${type}/${post[2]}/embed/captioned/`, provider: "Instagram" };
    }
  }

  if (["facebook.com", "m.facebook.com"].includes(host) && /\/posts\/|\/videos\/|^\/permalink\.php$/.test(url.pathname)) {
    const embed = new URL("https://www.facebook.com/plugins/post.php");
    embed.searchParams.set("href", url.href);
    embed.searchParams.set("show_text", "true");
    embed.searchParams.set("width", "500");
    return { ...preview, kind: "embed", src: embed.href, provider: "Facebook" };
  }

  if (/\.(mp4|webm|mov|m4v|ogv)$/i.test(url.pathname)) {
    return { ...preview, kind: "video", src: url.href, provider: "Video" };
  }
  if (/\.(jpe?g|png|webp|gif|avif|svg|bmp)$/i.test(url.pathname)) {
    return { ...preview, kind: "image", src: url.href, thumbnail: thumbnail ?? url.href, provider: "Image" };
  }

  // Unknown websites may disallow embedding. Keep their original link available.
  return preview;
}

export interface AdPreviewSource {
  ad_id: string;
  account_id?: string | null;
  thumbnail_url?: string | null;
  video_source_url?: string | null;
  video_url?: string | null;
  instagram_permalink?: string | null;
  effective_object_story_id?: string | null;
}

/** Direct media first; social posts remain available when a signed URL expires. */
export function getAdPreviews(ad: AdPreviewSource): AssetPreview[] {
  const previews: AssetPreview[] = [];
  const add = (preview: AssetPreview) => {
    if (preview.href && !previews.some((p) => p.src === preview.src && p.href === preview.href)) previews.push(preview);
  };
  for (const value of [ad.video_source_url, ad.video_url]) {
    const url = webUrl(value);
    if (!url) continue;
    const parsed = getAssetPreview({ preview_url: url.href });
    // Meta's `source` field can be a signed video URL without an extension.
    add(parsed.kind === "link" ? { ...parsed, kind: "video", src: url.href, provider: "Video" } : parsed);
  }
  const thumbnail = webUrl(ad.thumbnail_url)?.href;
  if (thumbnail) add({ href: thumbnail, thumbnail, kind: "image", src: thumbnail, provider: "Image" });
  const instagram = getAssetPreview({ preview_url: ad.instagram_permalink });
  if (instagram.provider === "Instagram") add(instagram);
  const story = ad.effective_object_story_id?.trim().match(/^(\d+)_(\d+)$/);
  if (story) add(getAssetPreview({ preview_url: `https://www.facebook.com/${story[1]}/posts/${story[2]}` }));
  if (ad.ad_id.trim()) {
    const manager = new URL("https://business.facebook.com/adsmanager/manage/ads/edit");
    manager.searchParams.set("selected_ad_ids", ad.ad_id);
    if (ad.account_id) manager.searchParams.set("act", ad.account_id);
    add({ href: manager.href, thumbnail: null, kind: "link", src: null, provider: "Ads Manager" });
  }
  return previews;
}
