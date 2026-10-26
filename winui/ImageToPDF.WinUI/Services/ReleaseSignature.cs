using System.Security.Cryptography;

namespace ImageToPDF.WinUI.Services;

/// <summary>
/// <c>SHA256SUMS.txt</c> の電子署名（ECDSA P-256 / SHA-256 / DER）を検証します。
///
/// SHA-256 の照合は「壊れていないこと」だけを示し、リリースの Assets を置き換えられる
/// 攻撃者はチェックサムファイルも一緒に差し替えられてしまいます。そのため、ハッシュの
/// 照合より前に、アプリに埋め込んだ公開鍵でチェックサムファイルの署名を検証します。
///
/// 秘密鍵はリポジトリに置かず、GitHub の保護された <c>release</c> environment の
/// シークレット（<c>RELEASE_SIGNING_KEY_B64</c>）にだけ置きます。生成・ローテーションは
/// <c>scripts/release_signing.py</c> を使います。
/// </summary>
internal static class ReleaseSignature
{
    /// <summary>署名ファイルのアセット名（DER 形式の ECDSA 署名）。</summary>
    internal const string SignatureAssetName = "SHA256SUMS.txt.sig";

    /// <summary>
    /// 署名検証用の公開鍵（ECDSA P-256 の SubjectPublicKeyInfo を Base64 にしたもの）。
    /// <c>scripts/release_signing.py sync-public-key</c> が書き換えます。空文字列のときは
    /// すべての自動更新を拒否します（フェイルクローズ）。
    /// </summary>
    internal const string SubjectPublicKeyInfoBase64 =
        "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE78+Rf0CrX9M2CgoOvJAfqinj8cXRtg43+j1WYdhhZPEH6p9bTaqSp4zkFZuUlqyOXGrdjEPDoaQWkOQnBkIyxA==";

    internal static bool IsConfigured => SubjectPublicKeyInfoBase64.Length > 0;

    /// <summary>埋め込み公開鍵で署名を検証します。検証できないときは例外を投げます。</summary>
    internal static void Verify(byte[] checksums, byte[] signature) =>
        Verify(checksums, signature, SubjectPublicKeyInfoBase64);

    /// <summary>
    /// 署名を検証します。<paramref name="publicKeyBase64"/> を指定する overload は
    /// 自己診断（<c>--selftest-update</c>）でのみ使います。
    /// </summary>
    internal static void Verify(byte[] checksums, byte[] signature, string publicKeyBase64)
    {
        if (checksums is null || checksums.Length == 0)
        {
            throw new InvalidOperationException("チェックサムファイルが空です。");
        }

        if (signature is null || signature.Length == 0)
        {
            throw new InvalidOperationException("更新ファイルの署名が見つかりません。");
        }

        if (string.IsNullOrWhiteSpace(publicKeyBase64))
        {
            throw new InvalidOperationException(
                "署名検証用の公開鍵が設定されていません。リリースページから手動で更新してください。");
        }

        try
        {
            using var ecdsa = ECDsa.Create();
            ecdsa.ImportSubjectPublicKeyInfo(Convert.FromBase64String(publicKeyBase64), out _);
            if (!ecdsa.VerifyData(
                    checksums,
                    signature,
                    HashAlgorithmName.SHA256,
                    DSASignatureFormat.Rfc3279DerSequence))
            {
                throw new InvalidOperationException("更新ファイルの署名を確認できませんでした。");
            }
        }
        catch (Exception error) when (
            error is CryptographicException or FormatException or ArgumentException
                or PlatformNotSupportedException)
        {
            throw new InvalidOperationException("更新ファイルの署名を確認できませんでした。", error);
        }
    }
}
