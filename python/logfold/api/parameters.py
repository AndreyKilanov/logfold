"""``extract_parameters()``: the values that a message gives to the variable positions of a template."""

from __future__ import annotations

from functools import lru_cache

from logfold._bridge import ExtractorHandle
from logfold.api._common import _mining, settings_mining
from logfold.config import MaskRule, MiningConfig
from logfold.engines.native import mining_to_dicts
from logfold.errors import ConfigError
from logfold.ext.mask_selection import MaskSelection
from logfold.model import Parameter, Template
from logfold.settings import Settings


@lru_cache(maxsize=16)
def _extractor(masks: tuple[MaskRule, ...], delimiters: str) -> ExtractorHandle:
    """Compile the masks and the delimiters once for every configuration that is in use."""
    plain_masks, _ = mining_to_dicts(MiningConfig(masks=masks, delimiters=delimiters))
    return ExtractorHandle(plain_masks, delimiters)


def extract_parameters(
    template: str | Template,
    message: str,
    *,
    masks: MaskSelection | None = None,
    mining: MiningConfig | None = None,
    config: Settings | None = None,
    delimiters: str | None = None,
) -> tuple[Parameter, ...] | None:
    """Give the values that a message has at the variable positions of a template.

    The message is masked and tokenized as the miner does, the tokens are aligned with the template, and every
    variable part is given as it was written in the message. A ``<*>`` token of the template gives one parameter named
    ``*`` with the whole token (the masked values inside it are not given again). A constant token that holds a masked
    value, such as ``id=<NUM>``, gives one parameter named by the rule (``num``); a rule that spans several words, such
    as ``ts``, gives one parameter for all of them.

    The template text is split at its single spaces, as the miner joins its tokens, so it must come from a run whose
    delimiters include the space (the default). The masks and the delimiters must be the ones that the template was
    mined with; the compiled masks are kept between calls, so calling this for many messages is cheap.

    Args:
        template: The text of a template, or a ``Template`` of a result.
        message: One record, as written in the log (without the part that the format cuts off).
        masks: Rules that replace the defaults, or mask sets and names such as ``"secrets"`` that run before them.
        mining: Full mining configuration; ``masks`` overrides its rules.
        config: Settings from a ``logfold.toml`` (:func:`logfold.load_config`), used where the call names no mining
            configuration itself.
        delimiters: The characters that separate tokens, replacing the ones of ``mining``; they must include the space.

    Returns:
        The parameters in the order of their positions (empty for a template with no variable part), or ``None`` when
        the message does not fit the template: it has another number of tokens, or a constant token differs.

    Raises:
        ConfigError: If a masking rule is invalid or the delimiters do not include the space.
        EngineError: If the native extension is unavailable.
    """
    text = template.text if isinstance(template, Template) else template
    base = mining if mining is not None else (settings_mining(config) if config is not None else None)
    resolved = _mining(base, None, None, None, None, masks, delimiters=delimiters)
    if " " not in resolved.delimiters:
        raise ConfigError(
            "the delimiters do not include the space",
            hint="a template joins its tokens with a space, so the values of a message can only be found when the "
            "run split tokens at spaces too",
        )
    (found,) = _extractor(resolved.masks, resolved.delimiters).extract(text, [message])
    return None if found is None else tuple(Parameter(*row) for row in found)
