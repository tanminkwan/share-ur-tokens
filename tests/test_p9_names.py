"""P9: pen names = nickname + the start of the key. Pure rules (arena/names.py)."""
from arena.names import display, nick_error, resolve

A = "aa11ff" + "0" * 58
B = "bb22ee" + "0" * 58
C = "aa11ee" + "1" * 58  # shares `aa11` with A


def test_p9a1_a_name_is_the_nickname_and_the_first_six_key_characters():
    assert display(A, "비단길", 6) == "비단길-aa11ff"
    assert display(A, "필명", 4) == "필명-aa11"


def test_p9a4_nickname_shape():
    assert nick_error("비단길", 16) is None
    assert nick_error("Silk🧵", 16) is None  # an emoji is a visible character
    assert nick_error("", 16)
    assert nick_error("가" * 17, 16)
    for bad in ("a b", "a-b", "a#b", "a\tb", "a\nb", "http-x", "HTTPS", "mem:x"):
        assert nick_error(bad, 16), bad
    assert nick_error(None, 16)


def test_p9b1_the_full_name_names_one_key():
    known = [(A, "비단길"), (B, "비단길")]
    assert resolve("비단길-aa11ff", known, 6).pub == A
    assert resolve("비단길-bb22ee", known, 6).pub == B


def test_p9b2_the_nickname_alone_names_the_only_one_with_it():
    assert resolve("비단길", [(A, "비단길"), (B, "물결")], 6).pub == A
    assert resolve(" 비단길 ", [(A, "비단길")], 6).pub == A  # spaces around are ignored


def test_p9b3_a_shared_nickname_is_told_apart_by_more_of_the_key():
    known = [(A, "비단길"), (C, "비단길"), (B, "비단길")]
    assert resolve("비단길-bb", known, 6).pub == B
    assert resolve("비단길-aa11f", known, 6).pub == A
    assert resolve("비단길-aa11e", known, 6).pub == C


def test_p9b4_several_left_means_refused_with_the_candidates_named_in_full():
    known = [(A, "비단길"), (B, "비단길")]
    m = resolve("비단길", known, 6)
    assert m.pub is None and m.error and len(m.candidates) == 2
    assert "비단길-aa11ff" in m.error and "비단길-bb22ee" in m.error
    m = resolve("비단길-aa", [(A, "비단길"), (C, "비단길")], 6)
    assert m.pub is None and "비단길-aa11ff" in m.error and "비단길-aa11ee" in m.error


def test_p9b4_nobody_means_not_found():
    for ref in ("물결", "비단길-cc", "비단길-zz", "-aa11ff", "", "aa11ff"):
        m = resolve(ref, [(A, "비단길")], 6)
        assert m.pub is None and "찾지 못했다" in m.error, ref


def test_p9_q3_nicknames_are_compared_without_case_and_keys_in_lower_case():
    known = [(A, "Silk")]
    assert resolve("silk", known, 6).pub == A
    assert resolve("SILK-AA11FF", known, 6).pub == A
    assert display(A, "Silk", 6) == "Silk-aa11ff"  # shown as chosen
