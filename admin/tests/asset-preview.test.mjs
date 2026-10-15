import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/assetPreview.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const { getAssetPreview, getAdPreviews } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

test("Drive file sharing formats resolve to a preview while preserving access resource keys", () => {
  for (const link of [
    "https://drive.google.com/file/d/asset_123-ABC/view?usp=sharing&resourcekey=key-123",
    "https://drive.google.com/open?id=asset_123-ABC&resourcekey=key-123",
    "https://drive.google.com/uc?export=download&id=asset_123-ABC&resourcekey=key-123",
  ]) {
    const preview = getAssetPreview({ preview_url: link });
    assert.equal(preview.kind, "embed");
    assert.equal(preview.src, "https://drive.google.com/file/d/asset_123-ABC/preview?resourcekey=key-123");
    assert.equal(preview.href, link);
    assert.equal(new URL(preview.thumbnail).searchParams.get("resourcekey"), "key-123");
  }
});

test("Instagram post and reel embeds exclude tracking query parameters", () => {
  for (const type of ["p", "reel", "reels", "tv"]) {
    const preview = getAssetPreview({ preview_url: `https://www.instagram.com/${type}/creative_123/?utm_source=share` });
    assert.equal(preview.kind, "embed");
    assert.equal(preview.src, `https://www.instagram.com/${type === "reels" ? "reel" : type}/creative_123/embed/captioned/`);
  }
});

test("signed direct media retains its full query string and correct playback kind", () => {
  for (const [file, kind] of [["creative.MP4", "video"], ["creative.webp", "image"]]) {
    const url = `https://cdn.example.com/${file}?signature=a%2Bb&expires=123`;
    const preview = getAssetPreview({ preview_url: url });
    assert.equal(preview.kind, kind);
    assert.equal(preview.src, url);
    assert.equal(preview.href, url);
  }
});

test("unsafe schemes, credentials, empty fields, and free text do not become links", () => {
  for (const value of [null, "", "  ", "Pending", "javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "//drive.google.com/file/d/abc/view", "https://user:password@example.com/asset.png"]) {
    const preview = getAssetPreview({ preview_url: value, thumbnail_url: value });
    assert.equal(preview.href, null);
    assert.equal(preview.src, null);
    assert.equal(preview.thumbnail, null);
  }
});

test("provider lookalike hosts and folder links do not become embedded frames", () => {
  for (const link of [
    "https://drive.google.com.attacker.example/file/d/abc/view",
    "https://instagram.com.attacker.example/p/abc/",
    "https://drive.google.com/drive/folders/abc",
    "https://drive.google.com/open?id=bad%2Fid",
    "https://example.com/creative-review",
  ]) {
    const preview = getAssetPreview({ preview_url: link });
    assert.equal(preview.kind, "link");
    assert.equal(preview.src, null);
    assert.equal(preview.href, link);
  }
});

test("a provided thumbnail can be viewed even when the original link is missing", () => {
  const thumbnail = "https://cdn.example.com/thumbnail.jpg";
  const preview = getAssetPreview({ preview_url: "Pending", thumbnail_url: ` ${thumbnail} ` });
  assert.equal(preview.kind, "image");
  assert.equal(preview.src, thumbnail);
  assert.equal(preview.href, thumbnail);
});

test("unknown source pages keep their original link alongside a usable thumbnail", () => {
  const preview = getAssetPreview({ preview_url: "https://example.com/review", thumbnail_url: "https://cdn.example.com/thumb.png" });
  assert.equal(preview.href, "https://example.com/review");
  assert.equal(preview.kind, "image");
  assert.equal(preview.src, "https://cdn.example.com/thumb.png");
});

test("Facebook post links become official embeds with their original URL encoded", () => {
  const link = "https://www.facebook.com/123/posts/456?story=abc&share=true";
  const preview = getAssetPreview({ preview_url: link });
  assert.equal(preview.kind, "embed");
  assert.equal(new URL(preview.src).origin, "https://www.facebook.com");
  assert.equal(new URL(preview.src).searchParams.get("href"), link);
});

test("video-only ads expose playback even without an is_video flag or poster", () => {
  for (const field of ["video_source_url", "video_url"]) {
    const url = "https://cdn.example.com/signed-source?signature=abc%2B123";
    const previews = getAdPreviews({ ad_id: "123", [field]: url });
    assert.equal(previews[0].kind, "video");
    assert.equal(previews[0].src, url);
  }
});

test("direct media precedes social embeds, with all available alternatives retained", () => {
  const previews = getAdPreviews({ ad_id: "123", video_source_url: "https://cdn.example.com/v.mp4", video_url: "https://cdn.example.com/v.mp4", thumbnail_url: "https://cdn.example.com/i.jpg", instagram_permalink: "https://www.instagram.com/reels/creative_123/", effective_object_story_id: "123_456" });
  assert.deepEqual(previews.map((p) => p.provider), ["Video", "Image", "Instagram", "Facebook", "Ads Manager"]);
  assert.match(previews[2].src, /\/reel\/creative_123\/embed\/captioned\//);
  assert.equal(new URL(previews[3].src).searchParams.get("href"), "https://www.facebook.com/123/posts/456");
});

test("invalid media never becomes an embed; ads without media retain their manager link", () => {
  const previews = getAdPreviews({ ad_id: "ad &1", account_id: "act_123", thumbnail_url: "javascript:alert(1)", video_url: "Pending", instagram_permalink: "https://instagram.com.evil.example/p/abc/", effective_object_story_id: "not_a_story" });
  assert.equal(previews.length, 1);
  assert.equal(previews[0].kind, "link");
  assert.equal(new URL(previews[0].href).searchParams.get("selected_ad_ids"), "ad &1");
  assert.equal(new URL(previews[0].href).searchParams.get("act"), "act_123");
  assert.deepEqual(getAdPreviews({ ad_id: "" }), []);
});

test("provider video links use their embed instead of being treated as a video file", () => {
  const previews = getAdPreviews({ ad_id: "123", video_url: "https://drive.google.com/file/d/abc/view" });
  assert.equal(previews[0].kind, "embed");
  assert.equal(previews[0].src, "https://drive.google.com/file/d/abc/preview");
});
