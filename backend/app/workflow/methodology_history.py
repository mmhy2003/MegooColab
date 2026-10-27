"""Every default methodology text each key has shipped with, as the SHA-256 of its UTF-8 text, oldest first;
the last is the current file in defaults/. On startup, a key whose latest version is still one of the older
defaults (nobody customised it) gets the current default as a new version (methodology.upgrade_defaults).

When you change a default text, append its new hash here: test_default_history_ends_with_the_current_texts
fails until you do.
"""

DEFAULT_HISTORY: dict[str, list[str]] = {
    "brainstorm": [
        "48f368064a035a3c5afec8b14889fd152d37d64cc517d10ff5ab44b14b8ce533",
        "c2776fe8cc214c15ed439d13acdbe031b3aaf79a51f6b716c93710ca8e90440a",
        "9b8f73e6adbc875b1b23294505ec303a8943ff7b91d7479451d6253a0ca5a393",
        "00277fef22ee863a94b51f13ee72976968543c59c6334b4cbffc1b092276381e",
    ],
    "design_revision": [
        "7b6bfa9f3eb82fdf3e709413ceb6f029ae88e91372eaa0462e06e1d0872db8fe",
    ],
    "plan": [
        "ee12eca000a1c412b2ff2d7d411acc22ee451d33151daa9fadd1a3a96b1ead8a",
        "58ee7f519d85c573068601ba3db066e97b220f24d480782220ab7759e03c59a5",
        "8f464937ab205b21f572c4bcb15d3f2f6957c246669cf1e13708f1a9d2efdea2",
        "23068a95b2704001cb364269186029b440a587ef4c915d5a953da5a7bae51309",
        "644c1efc069753f8cadb463fa6e252e618b4de849e9f583eba36dbf91f77f5a1",
    ],
    "build_implement": [
        "3387bdcacabcd579787950117b408e5b3029791ab55200b3b1f821dd8f2bb5c8",
        "0d22a13113db8efe4eb23f429968476f8291b68e75d2442bf54f74202746029f",
        "878805bab9a5a706dab6dc792e3b5497397eb554e523adf69e10d4083e4ef739",
        "8d0f27d067d4055581dd1291665e41ea30ddf13f638a59ba16f2f68885947eda",
        "ef7089bf7fc0663b20a713263ee7a0adbe615fab9f057d1dfbdb3620a3ed0494",
    ],
    "build_step_review": [
        "1040468db7144eb9bd6ef78eaab5a8f8a3d461436897d6ab442d648c5b29d33f",
        "bdad3a3e6d835653ac147e9234146c33574b38c72894bd2b5ad69a9e559963b9",
        "9193479e7f8ffca14daa85bbf047e22a2a157cc1c08501942da2308d3ef8f7df",
    ],
    "build_step_fix": [
        "fd5729364fa62da230ff345f9058ac228df7ce5ad3649700533f6ffde94dbade",
        "89558e6c9b2181777d0fc2ad07287cb56500b1e86754dbee6efb8c9b80a69dfe",
        "2566a6e6c85cb5af1d1a3859da5245590d8883f1e29c357d78eb587dc20055c0",
    ],
    "review_final": [
        "a3cf46bcf975acd92f185d2decb3bebe97981ef792054d9453061bfe56c29ea1",
        "56daf3ab279059f967226395aefca821a8c55b42f521f41237e657e7c2c5cfc7",
        "6db3cbdffef160f5f2695019694b23d3b23e820cf643ab250b072c5548e2e4a2",
    ],
    "review_fix": [
        "a423e90a0cb1645f5e3770bc2797007a953e38c64ded16f835ea5033fc641879",
        "c456582d385e92c9f3183bae3794e1181e413f721dfcd800a11f7abb229a1758",
    ],
    "finish": [
        "962d9a01582b0122e02cc13d84dda6f036f338a6c239b96e242e042ce46ccbe7",
        "1e6fcac079b77b9161d9a5f84f968f69afc6c94878baa43416e151a78537fed6",
        "bb3b5c3ecf5370c72bc20aab904aaec4c7b75d0562550ac92706d9632f30fec5",
    ],
}
