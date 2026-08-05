// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"

namespace RammsPixelStreaming
{
	/**
	 * Replace the default Pixel Streaming streamer's backbuffer video producer
	 * with the viewport MediaCapture producer once Pixel Streaming is ready.
	 *
	 * The stock backbuffer producer forwards every Slate window's backbuffer
	 * unfiltered; a second window of a different size (e.g. a persistent
	 * notification toast) then forces the capture pipeline to rebuild every
	 * frame and the stream stays black with no diagnostics. The viewport
	 * MediaCapture producer captures only the scene viewport and is immune.
	 * Details: doc/PIXEL_STREAMING_PLAN.md.
	 *
	 * No-op in the editor, on platforms without Pixel Streaming, and when no
	 * connection URL was given (no streaming intended).
	 */
	void InstallViewportProducerSwap();
} // namespace RammsPixelStreaming
