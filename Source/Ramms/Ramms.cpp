// Copyright Epic Games, Inc. All Rights Reserved.

#include "Ramms.h"
#include "Modules/ModuleManager.h"
#include "RammsPixelStreamingSetup.h"

#if RAMMS_WITH_GAMEINPUT
	#include "Containers/Ticker.h"
	#include "GameInputBaseModule.h"
	#include "HAL/PlatformTime.h"
#endif

class FRammsGameModule : public FDefaultGameModuleImpl
{
public:
	virtual void StartupModule() override
	{
		FDefaultGameModuleImpl::StartupModule();
		RammsPixelStreaming::InstallViewportProducerSwap();
		EnableGameInputBackgroundInput();
	}

	virtual void ShutdownModule() override
	{
#if RAMMS_WITH_GAMEINPUT
		FTSTicker::RemoveTicker(GameInputFocusTicker);
		GameInputFocusTicker.Reset();
#endif
		FDefaultGameModuleImpl::ShutdownModule();
	}

private:
	/**
	 * GameInput's default focus policy gives an unfocused app a blank reading, every controller axis
	 * at 0. A generic HID pad (the Backbone Pro) reports its sticks as 0..1 centred at 0.5, so the
	 * blank reading is both sticks pushed into a corner and the camera spins until the app is focused
	 * again. XInput pads keep their real state in the background; background input makes HID pads
	 * match them. Unreal creates the IGameInput on a background task at startup, so wait for it.
	 */
	void EnableGameInputBackgroundInput()
	{
#if RAMMS_WITH_GAMEINPUT
	#if GAME_INPUT_SUPPORT // defined by GameInputBase, which the module depends on when RAMMS_WITH_GAMEINPUT
		const double GiveUpTime = FPlatformTime::Seconds() + 60.0;
		GameInputFocusTicker = FTSTicker::GetCoreTicker().AddTicker(TEXT("RammsGameInputFocusPolicy"), 0.25f, [GiveUpTime](float) {
			if (IGameInput* GameInput = FGameInputBaseModule::GetGameInput())
			{
				GameInput->SetFocusPolicy(GameInputEnableBackgroundInput);
				UE_LOG(LogRamms, Log, TEXT("GameInput: background input enabled, so HID gamepads keep their real state while the app is unfocused"));
				return false;
			}
			return FPlatformTime::Seconds() < GiveUpTime;
		});
	#endif
#endif
	}

#if RAMMS_WITH_GAMEINPUT
	FTSTicker::FDelegateHandle GameInputFocusTicker;
#endif
};

IMPLEMENT_PRIMARY_GAME_MODULE(FRammsGameModule, Ramms, "Ramms");

DEFINE_LOG_CATEGORY(LogRamms)
