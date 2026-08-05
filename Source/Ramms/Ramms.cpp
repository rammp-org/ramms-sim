// Copyright Epic Games, Inc. All Rights Reserved.

#include "Ramms.h"
#include "Modules/ModuleManager.h"
#include "RammsPixelStreamingSetup.h"

class FRammsGameModule : public FDefaultGameModuleImpl
{
public:
	virtual void StartupModule() override
	{
		FDefaultGameModuleImpl::StartupModule();
		RammsPixelStreaming::InstallViewportProducerSwap();
	}
};

IMPLEMENT_PRIMARY_GAME_MODULE(FRammsGameModule, Ramms, "Ramms");

DEFINE_LOG_CATEGORY(LogRamms)
