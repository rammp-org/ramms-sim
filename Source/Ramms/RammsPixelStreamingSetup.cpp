// Copyright Epic Games, Inc. All Rights Reserved.

#include "RammsPixelStreamingSetup.h"

#include "Ramms.h"

#if RAMMS_WITH_PIXEL_STREAMING
	#include "Containers/Ticker.h"
	#include "IPixelStreaming2Module.h"
	#include "IPixelStreaming2Streamer.h"
	#include "Misc/CoreDelegates.h"
	#include "VideoProducerMediaCapture.h"
#endif

namespace RammsPixelStreaming
{

#if RAMMS_WITH_PIXEL_STREAMING
	static void SwapDefaultStreamerProducer(IPixelStreaming2Module& Module)
	{
		if (GIsEditor)
		{
			// Editor/PIE streaming has its own producer selection.
			return;
		}
		if (Module.GetDefaultConnectionURL().IsEmpty())
		{
			// No streaming requested this run; the default streamer has no
			// producer attached either — leave the GPU untaxed.
			return;
		}
		TSharedPtr<IPixelStreaming2Streamer> Streamer = Module.FindStreamer(Module.GetDefaultStreamerID());
		if (!Streamer)
		{
			// OnReady fires just before the module creates its default streamer,
			// so poll briefly until it exists.
			static double GiveUpTime = FPlatformTime::Seconds() + 30.0;
			if (FPlatformTime::Seconds() > GiveUpTime)
			{
				UE_LOG(LogRamms, Warning, TEXT("Pixel Streaming ready but default streamer never appeared; keeping stock video producer"));
				return;
			}
			FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateLambda(
													 [&Module](float) {
														 SwapDefaultStreamerProducer(Module);
														 return false; // one-shot; SwapDefaultStreamerProducer re-arms if needed
													 }),
				0.1f);
			return;
		}
		// Starts capturing after the next rendered frame and restarts itself on
		// viewport resize, so installing this early is safe.
		Streamer->SetVideoProducer(UE::PixelStreaming2::FVideoProducerMediaCapture::CreateActiveViewportCapture());
		UE_LOG(LogRamms, Log, TEXT("Pixel Streaming: switched default streamer to the viewport MediaCapture producer (immune to extra Slate windows; see doc/PIXEL_STREAMING_PLAN.md)"));
	}
#endif // RAMMS_WITH_PIXEL_STREAMING

	void InstallViewportProducerSwap()
	{
#if RAMMS_WITH_PIXEL_STREAMING
		FCoreDelegates::OnPostEngineInit.AddLambda(
			[]() {
				if (!IPixelStreaming2Module::IsAvailable())
				{
					return;
				}
				IPixelStreaming2Module& Module = IPixelStreaming2Module::Get();
				if (Module.IsReady())
				{
					SwapDefaultStreamerProducer(Module);
				}
				else
				{
					Module.OnReady().AddLambda(
						[](IPixelStreaming2Module& ReadyModule) {
							SwapDefaultStreamerProducer(ReadyModule);
						});
				}
			});
#endif // RAMMS_WITH_PIXEL_STREAMING
	}

} // namespace RammsPixelStreaming
