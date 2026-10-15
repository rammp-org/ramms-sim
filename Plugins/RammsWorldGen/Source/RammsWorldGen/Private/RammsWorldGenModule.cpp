// Copyright ATDev. All Rights Reserved.
#include "RammsWorldGenModule.h"

#include "Modules/ModuleManager.h"

DEFINE_LOG_CATEGORY(LogRammsWorldGen);

void FRammsWorldGenModule::StartupModule()
{
	UE_LOG(LogRammsWorldGen, Log, TEXT("RammsWorldGen module started (build 4)"));
}

void FRammsWorldGenModule::ShutdownModule()
{
}

IMPLEMENT_MODULE(FRammsWorldGenModule, RammsWorldGen)
