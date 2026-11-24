"""Every default methodology text each key has shipped with, as the SHA-256 of its UTF-8 text, oldest first;
the last is the current file in defaults/. On startup, a key whose latest version is still one of the older
defaults (nobody customised it) gets the current default as a new version (methodology.upgrade_defaults).

When you change a default text, append its new hash here: test_default_history_ends_with_the_current_texts
fails until you do.
"""

DEFAULT_HISTORY: dict[str, list[str]] = {
    "freestyle": [
        "533e10a68647b78784c2d0ce611fadea2170fdb7bd8daeb9ac6e9f10d356cebd",
        "58e7bf59ecdbf312be26bae501573daaa5d772f66540097754c6dbc988fb6dc9",
        "4310bb9e43ce82c1a10ead920eaf10daafb633dc477ac750c2d0702c18ea2ba5",
    ],
    "cron": [
        "6242ec4f5f17b35bb2d0db59ff6f610ea64f3edffde2a1ce36918f85c5433ada",
        "06683549a00eb5e59be95409cd6580447f0ed5453a4323bdbeba21f5de1f5204",
    ],
    "kb_draft": [
        "1b5d39673fc327354892589a11c95b7d8deac6e1121982b83bd60ba1716a8492",
    ],
    "pr_review": [
        "f117ba33749e48e554e25366550ca3ae550579a0541b7ed7425fa0d7e7026ed7",
        "4793dcdd1368afe9f8c28114c84d9f30b9a28046a8566f0b0b914255abdf4ec7",
    ],
    "pr_fix": [
        "b9b52da52cfcd977cd5c98f7865ffd01c9c192639182760a920ac99d9f3fb293",
        "026170a580a8710ac27f4efa940e6c355b8a678a0a8f85f69dcc4618a46a96c0",
        "3bb855eb6d64d837c33022c5e51062650245ca2343e5fbd8ad843d59915d9536",
    ],
    "brainstorm": [
        "48f368064a035a3c5afec8b14889fd152d37d64cc517d10ff5ab44b14b8ce533",
        "c2776fe8cc214c15ed439d13acdbe031b3aaf79a51f6b716c93710ca8e90440a",
        "9b8f73e6adbc875b1b23294505ec303a8943ff7b91d7479451d6253a0ca5a393",
        "00277fef22ee863a94b51f13ee72976968543c59c6334b4cbffc1b092276381e",
        "b20571982b08dfd817ef39072b2de6b88d80242bafce8f506147dc0bacef10a4",
        "c357f68b3c86e3e3a235d3ebd6a0e2fca21f055ff838da518671d1750491b7e1",
        "aca55f7d7c5300b6d2d08457e8b327072058ca0c82cfebb9bdcca2f0cb8cfb39",
    ],
    "design_revision": [
        "7b6bfa9f3eb82fdf3e709413ceb6f029ae88e91372eaa0462e06e1d0872db8fe",
        "d9808506b33c95dc9e61e879db98128db3d589ef06013de90f0f883ab6fcb663",
        "2033bae5b41b87aadfaf76d652bcbd0bddb722cc8555466db989fb3e9874ff0a",
        "a26bb58df0188a698dbf96042442db4497782280ac8ee33aae99b65821631959",
    ],
    "plan": [
        "ee12eca000a1c412b2ff2d7d411acc22ee451d33151daa9fadd1a3a96b1ead8a",
        "58ee7f519d85c573068601ba3db066e97b220f24d480782220ab7759e03c59a5",
        "8f464937ab205b21f572c4bcb15d3f2f6957c246669cf1e13708f1a9d2efdea2",
        "23068a95b2704001cb364269186029b440a587ef4c915d5a953da5a7bae51309",
        "644c1efc069753f8cadb463fa6e252e618b4de849e9f583eba36dbf91f77f5a1",
        "2dab4b58cba5dfbc49b9f2fbe69a92d1d38501bc2b4a83a532fa103c07679276",
    ],
    "build_implement": [
        "3387bdcacabcd579787950117b408e5b3029791ab55200b3b1f821dd8f2bb5c8",
        "0d22a13113db8efe4eb23f429968476f8291b68e75d2442bf54f74202746029f",
        "878805bab9a5a706dab6dc792e3b5497397eb554e523adf69e10d4083e4ef739",
        "8d0f27d067d4055581dd1291665e41ea30ddf13f638a59ba16f2f68885947eda",
        "ef7089bf7fc0663b20a713263ee7a0adbe615fab9f057d1dfbdb3620a3ed0494",
        "0e7dbe88ab3b98f5ce2b0add1227ee42b986b0aedeca502f8f978add24be1a50",
        "5a9d01b46dfc51b3d0195cbd78367346c185d8d3675d54e26e786e216531f030",
        "0b0ec55185d068fc3b4c1a000092002572967961bc5496419ce5145c402f9623",
    ],
    "build_step_review": [
        "1040468db7144eb9bd6ef78eaab5a8f8a3d461436897d6ab442d648c5b29d33f",
        "bdad3a3e6d835653ac147e9234146c33574b38c72894bd2b5ad69a9e559963b9",
        "9193479e7f8ffca14daa85bbf047e22a2a157cc1c08501942da2308d3ef8f7df",
        "f693cde408895d94dfe268a74934e7dd1253744406e4a9ea53877da1cb70ccac",
        "a2ee3f5a4b14c759ed3ec107fe7031b515c19e93c939ddd5f862b1010f3ebd95",
    ],
    "build_step_fix": [
        "fd5729364fa62da230ff345f9058ac228df7ce5ad3649700533f6ffde94dbade",
        "89558e6c9b2181777d0fc2ad07287cb56500b1e86754dbee6efb8c9b80a69dfe",
        "2566a6e6c85cb5af1d1a3859da5245590d8883f1e29c357d78eb587dc20055c0",
        "ec156899cf2e7a89edbf553ea4c6bec27dbcac0ed7b82f0612852a2ac9c41ce7",
        "49e9ce4c0774a05278c8ad4469b5c05b791c3d1cc2760e7070d122d53bfa78e7",
        "cb828f44efacd70dabc4e91e70f5b49653fce81893d5a7d62d5b816fc0f3dcfa",
    ],
    "review_final": [
        "a3cf46bcf975acd92f185d2decb3bebe97981ef792054d9453061bfe56c29ea1",
        "56daf3ab279059f967226395aefca821a8c55b42f521f41237e657e7c2c5cfc7",
        "6db3cbdffef160f5f2695019694b23d3b23e820cf643ab250b072c5548e2e4a2",
        "2cbb6ef94c2c9b5ec9b75ad286ab5f3d697dd513dee091ec545da9778838652f",
        "2470be6753c0b87959e37a7de3f3f8a40476884fc770934beb443c9062e328f5",
    ],
    "review_fix": [
        "a423e90a0cb1645f5e3770bc2797007a953e38c64ded16f835ea5033fc641879",
        "c456582d385e92c9f3183bae3794e1181e413f721dfcd800a11f7abb229a1758",
        "9effeeb0d717ec0812ba3d98dca4c017d67f0f628b69736cf0806c603b43fb94",
        "5e126180816eef2afe46ee4dbf150b53167c9b174d3059f40f96c744bcd2857b",
    ],
    "finish_fix": [
        "3dca6fe6c9381ac9aacf3fbc65fd44a3915f9ae18f920199e2400e9472f66c28",
        "dcce1cd87027281e8de3f449d56f21dc5c23d20bd1d4c0978036728f7af739a4",
    ],
    "finish_fix_review": [
        "00a698ab88aa2d0a625162891769c0b87fe8553dc7b609fbf1546262979a01fe",
    ],
    "finish": [
        "962d9a01582b0122e02cc13d84dda6f036f338a6c239b96e242e042ce46ccbe7",
        "1e6fcac079b77b9161d9a5f84f968f69afc6c94878baa43416e151a78537fed6",
        "bb3b5c3ecf5370c72bc20aab904aaec4c7b75d0562550ac92706d9632f30fec5",
        "c3ec894eb50e6d7c5326246b49e3dac9d8198154010f697e59262c238c91093a",
        "5905ad05e2e35d18aa1367dd78e9d22e8b9eb99f88e08a2bfe3f55eb2db7222c",
        "f658da73ac2a20f3f721758e426f8cf9cda77c28795a974dc7cf1bd52e5a83ca",
        "ec8efb7994e8baf0987ca423fcaa265dc150de2cb25f06c7706844dec1642831",
        "a3147a058f56f62023712421d4a418ca989b58c081844bf60909ec9c30740c91",
        "79e8fcc2e6de619a35e5cf747df64fc03d6fd8381cc971a0f329b4a9c02bc371",
    ],
}
