"""Synced from upstream packages/core/tests/unit-test/siwc-public-entry.test.ts."""


class TestSiwcPublicEntry:
    def test_public_entry_reexports_existing_implementation(self):
        import midscene.core.siwc as public
        from midscene.core import siwc as internals

        assert public.refresh_siwc_credentials is internals.refresh_siwc_credentials
        assert public.create_siwc_authorization is internals.create_siwc_authorization
        assert public.exchange_siwc_code is internals.exchange_siwc_code
        assert public.parse_siwc_callback is internals.parse_siwc_callback
        error = public.SiwcError("fixture")
        assert type(error).__name__ == "SiwcError"
        assert isinstance(error, internals.SiwcError)
